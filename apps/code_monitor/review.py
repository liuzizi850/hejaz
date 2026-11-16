import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from apps.code_monitor.batching import FileChunk, render_batch
from apps.code_monitor.extract import (
    MODEL_CALL_TIMEOUT_SECONDS,
    ModelCallError,
    _first_json_array,
    _relax_json,
    _strip_model_wrapper,
)
from apps.code_monitor.screening import _walk, resolved_path_is_inside

MAX_SNIPPET_FILES = 6
MAX_SNIPPET_CHARS = 20000
MAX_FILE_INDEX_CHARS = 200_000
_FILE_WINDOW_CHARS = 4000

SOURCE_SUFFIXES = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".vue", ".mjs", ".cjs",
    ".java", ".go", ".php", ".cs", ".kt", ".rb", ".xml",
}

VERDICT_LABEL = {
    "implemented": "已实现",
    "partial": "部分实现",
    "missing": "未找到",
    "contradict": "与需求不一致",
    "uncheckable": "无法检查",
}
OMISSION_LABEL = {
    "branch": "分支遗漏",
    "validation": "校验遗漏",
    "chain": "链路遗漏",
    "symmetry": "对称遗漏",
    "i18n": "国际化问题",
    "defect": "明显缺陷",
}
VULN_LABEL = {
    "secret": "硬编码密钥",
    "sql_command": "SQL 或命令拼接",
    "path_traversal": "路径穿越",
    "eval": "动态执行",
    "missing_auth": "鉴权缺失",
}
_VERDICTS = set(VERDICT_LABEL) - {"uncheckable"}
_OMISSION_KINDS = set(OMISSION_LABEL)
_VULN_KINDS = set(VULN_LABEL)

_STOP = {
    "的", "了", "和", "与", "或", "在", "是", "有", "为", "及", "并", "对", "从",
    "把", "被", "这", "那", "一个", "进行", "可以", "需要", "支持", "功能", "如果",
    "以及", "通过", "进行", "the", "and", "for", "with", "this", "that", "from",
}
_SYNONYMS = {
    "国际化": ["i18n", "locale", "locales", "translation"],
    "多语言": ["i18n", "locale", "locales"],
    "登录": ["login", "signin", "sign_in"],
    "密码": ["password", "passwd"],
    "手机": ["phone", "mobile"],
    "订单": ["order"],
    "活动": ["activity", "event"],
    "购票": ["ticket", "purchase"],
    "票券": ["ticket", "voucher"],
    "余额": ["balance"],
    "流水": ["flow", "ledger"],
    "冻结": ["freeze", "frozen"],
    "扣款": ["deduct", "purchase"],
    "扣减": ["deduct"],
    "用户": ["user"],
    "支付": ["pay", "payment"],
    "权限": ["auth", "permission"],
    "注册": ["register", "signup"],
    "验证码": ["captcha", "sms"],
    "删除": ["delete", "remove"],
    "查询": ["query", "list"],
    "修改": ["update", "edit"],
    "新增": ["create", "add"],
    "上传": ["upload"],
    "下载": ["download"],
}
_SYMBOL = re.compile(
    r"(?m)^\s*(?:export\s+default\s+|export\s+)?(?:async\s+)?(?:def|class|function)\s+([A-Za-z_][\w]*)"
)
_VULN_RULES = [
    ("secret", re.compile(
        r"(?i)(?:api[_-]?key|secret|password|access[_-]?token|private[_-]?key)\s*[:=]\s*['\"][^'\"]{8,}['\"]"
    )),
    ("eval", re.compile(r"(?i)\beval\s*\(|new\s+Function\s*\(")),
    ("sql_command", re.compile(
        r"(?i)execute\s*\(\s*f['\"]|cursor\.execute\s*\(\s*f['\"]|\bos\.system\s*\(|shell\s*=\s*True"
    )),
    ("path_traversal", re.compile(r"(?i)open\s*\([^)]*(?:request\.|params\[|query\[)")),
    ("missing_auth", re.compile(r"(?i)permission_classes\s*=\s*\[\s*\]|AllowAny")),
    ("insecure_tls", re.compile(r"verify\s*=\s*False")),
    ("unsafe_deserialize", re.compile(r"pickle\.loads?\s*\(|yaml\.load\s*\((?![^)\n]*SafeLoader)")),
    ("debug", re.compile(r"(?i)\bDEBUG\s*=\s*True\b")),
]
_DEFECT_QUESTION = re.compile(r"漏洞|缺陷|\bbugs?\b|安全问题|代码质量", re.IGNORECASE)
_FRONTEND_SUFFIXES = {".vue", ".jsx", ".tsx", ".swift", ".dart", ".m", ".mm"}
_BACKEND_SUFFIXES = {".java", ".py", ".go", ".php", ".cs", ".rb"}
_UI_MARK = re.compile(
    r"颜色|红字|红色|灰色|绿色|高亮|样式|字体|图标|跳转|文案|按钮名称|控件名称|"
    r"字段展示|展示字段|显示字段|不可见|隐藏该入口"
)
_DATA_MARK = re.compile(r"校验|扣减|扣款|落库|入库|写入数据库|审批|退款|生成.+流水")
_MAX_CODE_VULNS = 30
_MAX_CODE_DEFECTS = 20
_VULN_TEXT = {
    "secret": (
        "代码中存在硬编码密钥",
        "在页面、接口响应或前端资源中搜索该密钥是否明文出现",
        "响应和页面中不应出现密钥原文",
    ),
    "sql_command": (
        "查询或系统命令由字符串拼接而成",
        "在相关输入中提交引号或命令分隔符，看响应是否把输入拼进查询或系统命令",
        "输入应被当作数据，不应改变查询或执行命令",
    ),
    "path_traversal": (
        "文件路径直接使用了外部输入",
        "在文件路径参数中提交包含 ../ 的值，看是否读到预期目录之外的文件",
        "应拒绝访问目录之外的文件",
    ),
    "eval": (
        "存在动态执行代码的写法",
        "在进入这段逻辑的输入中提交代码片段，看是否被执行",
        "输入不应被当作代码执行",
    ),
    "missing_auth": (
        "接口可见地放开了登录或权限校验",
        "不带登录态调用该接口，看是否仍返回业务数据",
        "未登录访问应被拒绝",
    ),
    "insecure_tls": (
        "请求关闭了证书校验",
        "抓包或中间人访问该请求，看是否仍成功",
        "应校验证书，关闭校验时不应放行",
    ),
    "unsafe_deserialize": (
        "使用了不安全的反序列化",
        "向该入口提交不可信数据，看是否被反序列化执行",
        "不可信数据不应被 pickle 或非安全 YAML 加载",
    ),
    "debug": (
        "调试开关处于打开状态",
        "按调试配置访问接口或页面，看是否暴露堆栈、内部信息",
        "对外环境不应打开调试开关",
    ),
}

SPLIT_SYSTEM = """你是测试分析员。把用户需求拆成检查点，供后续对照代码。

只输出一个 JSON 数组，不要 Markdown，不要解释。

每个元素是对象：
- text: 字符串。一个可单独核对的行为，包含动作和预期。不要把多件事写进同一条。
- checkable: 布尔。能对照代码判断有没有做则为 true。纯体验、主观感受、没有具体行为的句子为 false。
- reason: 字符串。checkable 为 false 时说明为什么无法检查；为 true 时用空字符串。

规则：
1. 不要编造需求里没有的功能。
2. 一条只写一件事。
3. 「是否做了某项能力」「有没有实现某项能力」只要这项能力能在代码里看出，就是可检查需求。例如：是否做了国际化、是否做了权限校验、是否记录操作日志。
4. 只有纯感受才标 false，例如「体验要好」「界面好看」。
5. 「代码有没有漏洞」「有没有 bug」「有没有明显缺陷」是可检查需求，text 写「检查整个代码是否存在明显漏洞和缺陷」。
6. 没有可拆内容时输出 []。
7. 当前只有后端代码：页面展示哪些字段、颜色、文案、按钮样式、点击跳转标 false，reason 写「这是前端表现，后端代码对不上」。校验、金额、状态、落库、余额、审批、流水仍标 true。"""

JUDGE_SYSTEM = """你是测试分析员。根据给定代码片段，判断一条需求点的实现、遗漏和明显漏洞。片段以「文件: <路径>」开头。

只输出一个 JSON 对象，不要 Markdown，不要解释。

字段：
- verdict: implemented、partial、missing、contradict 之一
  implemented: 片段里能看到该需求点的主流程
  partial: 有入口，但缺条件、校验、失败处理或后半段
  missing: 片段里没有该需求点
  contradict: 片段里的行为与需求相反
- evidence_file: 字符串。结论所依据的文件路径，必须来自片段开头的「文件:」。missing 时用空字符串。
- evidence_note: 字符串。给测试人员看的一句话，说明代码里实际有什么。不要贴大段代码。
- omissions: 数组。仅当 verdict 是 implemented 或 partial。每项：
  - kind: branch、validation、chain、symmetry 之一
  - gap: 缺了什么，用测试语言
  - precondition: 前置条件，看不出则空字符串
  - steps: 三到五步测试步骤
  - expected: 预期。需求没写具体文案时写应有的失败或拦截结果，不要编造界面文案
  - evidence_file: 已有主流程所在文件
- vulnerabilities: 数组。只报告片段里明显的问题。每项：
  - kind: secret、sql_command、path_traversal、eval、missing_auth 之一
  - risk: 测试人员能看懂的一句话风险
  - how_to_test: 怎么测，描述请求或操作以及看什么结果
  - expected: 期望的安全结果
  - evidence_file: 文件路径

规则：
1. 只根据给定片段，不要用常识补功能。
2. 遗漏必须能指出旁边已经存在的代码。需求没写、片段里也没有相邻实现的功能，不要报遗漏。
3. 片段主题对不上这条需求时，不要写成功能没做。verdict 用 missing，evidence_note 写「无法从给定片段判断」。只有片段明确就是这条功能、并且看不到该行为时，才说明缺了什么。没有把握时 omissions 和 vulnerabilities 用空数组。
4. 当前是后端代码：不要把页面展示、颜色、文案、跳转写成遗漏。只写数据、校验、状态和存储上的缺口。"""


@dataclass
class IndexedFile:
    source_file: str
    text: str
    symbols: str


@dataclass
class Omission:
    kind: str
    gap: str
    precondition: str
    steps: str
    expected: str
    path: str


@dataclass
class Vulnerability:
    kind: str
    risk: str
    how_to_test: str
    expected: str
    path: str


@dataclass
class Finding:
    number: int
    text: str
    verdict: str
    advice: str
    priority: str
    evidence_path: str
    evidence_note: str
    omissions: list[Omission] = field(default_factory=list)
    vulnerabilities: list[Vulnerability] = field(default_factory=list)


@dataclass
class ReviewReport:
    requirement: str
    findings: list[Finding]
    truncated: bool = False


_I18N_PATH = re.compile(r"(^|/)(locales?|i18n|lang|translations?)(/|$)", re.IGNORECASE)
_I18N_CODE = re.compile(
    r"vue-i18n|createI18n|useI18n|\$t\s*\(|i18n\.t\s*\(|gettext|ugettext|"
    r"django\.utils\.translation|react-i18next|useTranslation|FormattedMessage"
)
_I18N_QUESTION = re.compile(r"国际化|多语言|本地化|i18n|internationali[sz]ation", re.IGNORECASE)
_LANG_NAMES = {
    "zh", "zh-cn", "zh-hans", "zh-hant", "zh_cn", "cn",
    "en", "en-us", "en-gb", "en_us",
    "ja", "ja-jp", "jp", "ko", "ko-kr", "fr", "de", "es",
}
_LANG_LABEL = {
    "zh": "中文", "zh-cn": "中文", "zh-hans": "中文", "zh-hant": "中文", "zh_cn": "中文", "cn": "中文",
    "en": "英文", "en-us": "英文", "en-gb": "英文", "en_us": "英文",
    "ja": "日文", "ja-jp": "日文", "jp": "日文",
    "ko": "韩文", "ko-kr": "韩文",
}
_JS_KEY = re.compile(r"([A-Za-z_][\w]*)\s*:")
_JS_KEY_SKIP = {"return", "function", "if", "else", "import", "export", "const", "let", "var", "default", "from", "new"}
_EMPTY_I18N_VALUE = re.compile(r"""([A-Za-z_][\w]*)\s*:\s*(?:''|"")""")
_UI_SUFFIXES = {".vue", ".jsx", ".tsx"}
_I18N_CALL = re.compile(r"\$t\s*\(|\bi18n\b|\bt\s*\(\s*['\"]|useI18n|formatMessage|useTranslation")
_MAX_I18N_OMISSIONS = 12


def build_index(root: Path) -> list[IndexedFile]:
    indexed = []
    for path in _walk(root):
        if not resolved_path_is_inside(path, root):
            continue
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            continue
        suffix = path.suffix.lower()
        if suffix not in SOURCE_SUFFIXES and not (suffix == ".json" and _I18N_PATH.search(relative)):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not text.strip():
            continue
        body = text[:MAX_FILE_INDEX_CHARS]
        indexed.append(IndexedFile(relative, body, " ".join(_SYMBOL.findall(body))))
    return indexed


def search_tokens(text: str) -> list[str]:
    found = []
    for word in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text.lower()):
        if word not in _STOP:
            found.append(word)
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        if chunk not in _STOP:
            found.append(chunk if len(chunk) <= 8 else chunk[:8])
        for index in range(len(chunk) - 1):
            gram = chunk[index:index + 2]
            if gram not in _STOP:
                found.append(gram)
    expanded = []
    for token in found:
        for word, synonyms in _SYNONYMS.items():
            if word in token:
                expanded.extend(synonyms)
    return list(dict.fromkeys(found + expanded))


def retrieve_snippets(files: list[IndexedFile], requirement_point: str) -> list[FileChunk]:
    tokens = search_tokens(requirement_point)
    if not tokens:
        return []
    ranked = []
    for item in files:
        score = _score(item, tokens)
        if score:
            ranked.append((score, item.source_file, item))
    ranked.sort(key=lambda pair: (-pair[0], pair[1]))
    chosen = []
    for _rank, _name, item in ranked[:MAX_SNIPPET_FILES]:
        body = _window(item.text, tokens, _FILE_WINDOW_CHARS)
        if not body.strip():
            continue
        candidate = FileChunk(item.source_file, body)
        if chosen and len(render_batch(chosen + [candidate])) > MAX_SNIPPET_CHARS:
            break
        chosen.append(candidate)
    return chosen


def code_surface(files: list[IndexedFile]) -> str:
    front = back = 0
    for item in files:
        suffix = Path(item.source_file).suffix.lower()
        if suffix in _FRONTEND_SUFFIXES:
            front += 1
        elif suffix in _BACKEND_SUFFIXES:
            back += 1
    if back and not front:
        return "backend"
    if front and not back:
        return "frontend"
    return "mixed"


def is_frontend_only(text: str) -> bool:
    if not _UI_MARK.search(text or ""):
        return False
    return _DATA_MARK.search(text or "") is None


def review_repository(config, root: Path, requirement: str, on_progress=None) -> ReviewReport:
    from apps.code_monitor.acquire import AcquireError

    text = (requirement or "").strip()
    if not text:
        raise AcquireError("请填写需求")
    files = build_index(root)
    if not files:
        raise AcquireError("没有找到可检查的源代码")
    _progress(on_progress, 10)
    surface = code_surface(files)
    checkpoints, truncated = split_checkpoints(config, text, surface)
    if surface == "backend":
        for item in checkpoints:
            if is_frontend_only(item["text"]):
                item["checkable"] = False
                item["reason"] = "这是页面展示、颜色或跳转，当前代码是后端"
    if not checkpoints:
        _progress(on_progress, 100)
        return ReviewReport(
            requirement=text,
            findings=[review_code_issues(files, 1, text)],
            truncated=False,
        )
    _progress(on_progress, 20)
    findings = []
    total = len(checkpoints)
    for index, checkpoint in enumerate(checkpoints, start=1):
        findings.append(_review_one(config, files, index, checkpoint, surface))
        _progress(on_progress, 20 + int(index * 80 / total))
    return ReviewReport(requirement=text, findings=findings, truncated=truncated)


def split_checkpoints(config, requirement: str, surface: str = "mixed") -> tuple[list[dict], bool]:
    user = requirement
    if surface == "backend":
        user += "\n\n当前只有后端代码。页面展示、颜色、文案和跳转不要标成可检查。"
    payload = _call_json(config, SPLIT_SYSTEM, user, "list")
    kept = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        kept.append({
            "text": text,
            "checkable": _as_bool(item.get("checkable"), default=True),
            "reason": str(item.get("reason") or "").strip() or "需求太笼统，无法对照代码",
        })
    return _keep_capability_checkpoints(requirement, kept), False


def normalize_finding(number: int, text: str, payload: dict, known: list[str], snippets: list[FileChunk]) -> Finding:
    verdict = str(payload.get("verdict") or "").strip()
    if verdict not in _VERDICTS:
        verdict = "missing"
    evidence = _match_file(str(payload.get("evidence_file") or ""), known)
    note = str(payload.get("evidence_note") or "").strip()
    if verdict in {"implemented", "partial", "contradict"} and not evidence:
        verdict = "missing"
        note = "未检索到能支撑结论的代码"
    omissions = []
    if verdict in {"implemented", "partial"}:
        raw_omissions = payload.get("omissions")
        if isinstance(raw_omissions, list):
            for item in raw_omissions:
                parsed = _omission(item, known)
                if parsed:
                    omissions.append(parsed)
    vulnerabilities = []
    raw_vulns = payload.get("vulnerabilities")
    if isinstance(raw_vulns, list):
        for item in raw_vulns:
            parsed = _vulnerability(item, known)
            if parsed:
                vulnerabilities.append(parsed)
    seen = {(item.kind, item.path) for item in vulnerabilities}
    for item in regex_vulnerabilities(snippets):
        if (item.kind, item.path) not in seen:
            vulnerabilities.append(item)
            seen.add((item.kind, item.path))
    if verdict == "missing" and not note:
        note = "未检索到相关代码"
    return _finish(number, text, verdict, evidence if verdict != "missing" else "", note, omissions, vulnerabilities)


def regex_vulnerabilities(snippets: list[FileChunk]) -> list[Vulnerability]:
    found = []
    seen = set()
    for snippet in snippets:
        if _is_test_path(snippet.source_file):
            continue
        for kind, pattern in _VULN_RULES:
            if (kind, snippet.source_file) in seen:
                continue
            if pattern.search(snippet.text):
                risk, how_to_test, expected = _VULN_TEXT[kind]
                found.append(Vulnerability(kind, risk, how_to_test, expected, snippet.source_file))
                seen.add((kind, snippet.source_file))
    return found


def summary_counts(findings: list[Finding]) -> dict:
    return {
        "total": len(findings),
        "high": sum(1 for item in findings if item.priority == "高"),
        "light": sum(
            1 for item in findings
            if item.verdict == "implemented" and not item.omissions and not item.vulnerabilities
        ),
        "missing": sum(1 for item in findings if item.verdict == "missing"),
        "vulnerabilities": sum(len(item.vulnerabilities) for item in findings),
        "uncheckable": sum(1 for item in findings if item.verdict == "uncheckable"),
    }


def call_model(config, system: str, user: str) -> str:
    from apps.requirement_analysis.models import AIModelService

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    async def _limited():
        return await asyncio.wait_for(
            AIModelService.call_openai_compatible_api(config, messages, max_tokens=4096),
            timeout=MODEL_CALL_TIMEOUT_SECONDS,
        )

    try:
        result = asyncio.run(_limited())
    except TimeoutError as exc:
        raise TimeoutError("模型调用超时") from exc
    message = (result["choices"][0].get("message") or {})
    content = message.get("content") or ""
    if not str(content).strip():
        content = message.get("reasoning_content") or ""
    return str(content)


def _review_one(config, files: list[IndexedFile], number: int, checkpoint: dict, surface: str = "mixed") -> Finding:
    text = checkpoint["text"]
    if _is_defect_scan(text):
        return review_code_issues(files, number, text)
    if _is_i18n_checkpoint(text):
        return review_i18n(files, number, text)
    if not checkpoint["checkable"]:
        return _finish(
            number, text, "uncheckable", "", checkpoint["reason"], [], [],
        )
    snippets = retrieve_snippets(files, text)
    known = [item.source_file for item in snippets]
    if not snippets:
        return _finish(number, text, "missing", "", "未检索到相关代码", [], [])
    payload = _call_json(config, JUDGE_SYSTEM, _judge_user(text, snippets, surface), "dict")
    if surface == "backend" and isinstance(payload.get("omissions"), list):
        payload["omissions"] = [
            item for item in payload["omissions"]
            if not (isinstance(item, dict) and _UI_MARK.search(str(item.get("gap") or "")))
        ]
    finding = normalize_finding(number, text, payload, known, snippets)
    if (
        surface == "backend"
        and finding.verdict == "partial"
        and not finding.omissions
        and not finding.vulnerabilities
    ):
        finding.verdict = "implemented"
        finding.advice = _advice("implemented", [], [])
        finding.priority = _priority("implemented", [], [])
    return finding


def _finish(number, text, verdict, evidence, note, omissions, vulnerabilities) -> Finding:
    return Finding(
        number=number,
        text=text,
        verdict=verdict,
        advice=_advice(verdict, omissions, vulnerabilities),
        priority=_priority(verdict, omissions, vulnerabilities),
        evidence_path=evidence,
        evidence_note=note,
        omissions=omissions,
        vulnerabilities=vulnerabilities,
    )


def _advice(verdict: str, omissions: list[Omission], vulnerabilities: list[Vulnerability]) -> str:
    if verdict == "uncheckable":
        return "需求太笼统，需要产品补充后再测"
    if verdict == "contradict":
        return "按代码实际行为做缺陷验证，预期仍以需求原文为准"
    if verdict == "missing":
        if vulnerabilities:
            return "先跟开发确认未实现，并补安全测试"
        return "先跟开发确认未实现"
    if omissions and vulnerabilities:
        return "围绕缺口加测，并补安全测试"
    if omissions or verdict == "partial":
        return "围绕缺口加测"
    if vulnerabilities:
        return "主流程抽一条即可，并补安全测试"
    return "主流程抽一条即可"


def _priority(verdict: str, omissions: list[Omission], vulnerabilities: list[Vulnerability]) -> str:
    if verdict == "contradict":
        return "高"
    if verdict == "partial":
        return "高"
    if verdict in {"implemented", "missing"} and (omissions or vulnerabilities):
        return "高"
    if verdict == "implemented":
        return "低"
    return "中"


def _omission(item, known: list[str]) -> Omission | None:
    if not isinstance(item, dict):
        return None
    kind = str(item.get("kind") or "").strip()
    gap = str(item.get("gap") or "").strip()
    path = _match_file(str(item.get("evidence_file") or ""), known)
    if kind not in _OMISSION_KINDS or not gap or not path:
        return None
    expected = str(item.get("expected") or "").strip() or "应有明确的失败或拦截结果，具体文案以需求为准"
    steps = _as_steps(item.get("steps")) or gap
    return Omission(
        kind=kind,
        gap=gap,
        precondition=str(item.get("precondition") or "").strip(),
        steps=steps,
        expected=expected,
        path=path,
    )


def _vulnerability(item, known: list[str]) -> Vulnerability | None:
    if not isinstance(item, dict):
        return None
    kind = str(item.get("kind") or "").strip()
    risk = str(item.get("risk") or "").strip()
    path = _match_file(str(item.get("evidence_file") or ""), known)
    if kind not in _VULN_KINDS or not risk or not path:
        return None
    fallback_risk, fallback_how, fallback_expected = _VULN_TEXT[kind]
    return Vulnerability(
        kind=kind,
        risk=risk or fallback_risk,
        how_to_test=str(item.get("how_to_test") or "").strip() or fallback_how,
        expected=str(item.get("expected") or "").strip() or fallback_expected,
        path=path,
    )


def _is_i18n_checkpoint(text: str) -> bool:
    return bool(_I18N_QUESTION.search(text or ""))


def _is_defect_scan(text: str) -> bool:
    return bool(_DEFECT_QUESTION.search(text or ""))


def _keep_capability_checkpoints(requirement: str, kept: list[dict]) -> list[dict]:
    for item in kept:
        if _is_i18n_checkpoint(item["text"]) or _is_defect_scan(item["text"]):
            item["checkable"] = True
    for matcher in (_is_i18n_checkpoint, _is_defect_scan):
        if matcher(requirement) and not any(matcher(item["text"]) for item in kept):
            kept.append({"text": requirement.strip(), "checkable": True, "reason": ""})
    return kept


def review_code_issues(files: list[IndexedFile], number: int, text: str = "") -> Finding:
    title = (text or "").strip() or "检查整个代码是否存在明显漏洞和缺陷"
    vulnerabilities = []
    omissions = []
    seen_vulns = set()
    seen_defects = set()
    scanned = 0
    for item in files:
        if _is_test_path(item.source_file):
            continue
        scanned += 1
        for vuln in regex_vulnerabilities([FileChunk(item.source_file, item.text)]):
            key = (vuln.kind, vuln.path)
            if key in seen_vulns or len(vulnerabilities) >= _MAX_CODE_VULNS:
                continue
            vulnerabilities.append(vuln)
            seen_vulns.add(key)
        if item.source_file in seen_defects or len(omissions) >= _MAX_CODE_DEFECTS:
            continue
        defect = _swallowed_exception(item)
        if defect:
            omissions.append(defect)
            seen_defects.add(item.source_file)
    evidence = ""
    if vulnerabilities:
        evidence = vulnerabilities[0].path
    elif omissions:
        evidence = omissions[0].path
    note = f"已扫描 {scanned} 个源码文件，发现明显漏洞 {len(vulnerabilities)} 条、明显缺陷 {len(omissions)} 条。"
    if len(vulnerabilities) >= _MAX_CODE_VULNS or len(omissions) >= _MAX_CODE_DEFECTS:
        note += "问题较多，报告只列出前若干条。"
    verdict = "partial" if vulnerabilities or omissions else "implemented"
    finding = _finish(number, title, verdict, evidence, note, omissions, vulnerabilities)
    if vulnerabilities and omissions:
        finding.advice = "按补测用例和安全测试点逐条验证"
    elif vulnerabilities:
        finding.advice = "按安全测试点逐条验证"
    elif omissions:
        finding.advice = "按补测用例验证这些缺陷"
    else:
        finding.advice = "未发现明显漏洞和缺陷，可抽查关键功能后再测"
        finding.priority = "低"
    return finding


def _swallowed_exception(item: IndexedFile) -> Omission | None:
    lines = item.text.splitlines()
    for index, line in enumerate(lines):
        if not re.search(r"\bexcept\b", line) or ":" not in line:
            continue
        rest = line.split(":", 1)[1].strip()
        swallowed = rest == "pass" or rest == "..." or rest.startswith("pass ") or rest.startswith("...")
        if not swallowed:
            for nxt in lines[index + 1:index + 4]:
                stripped = nxt.strip()
                if not stripped:
                    continue
                swallowed = stripped == "pass" or stripped == "..."
                break
        if not swallowed:
            continue
        return Omission(
            kind="defect",
            gap=f"{item.source_file} 第 {index + 1} 行捕获异常后直接忽略",
            precondition="能构造触发该段异常的输入或数据",
            steps="触发这段被捕获的异常，查看页面提示、接口响应和日志",
            expected="应给出明确的失败结果，不应把异常静默吞掉",
            path=item.source_file,
        )
    return None


def review_i18n(files: list[IndexedFile], number: int, text: str) -> Finding:
    locale_files = []
    call_files = []
    for item in files:
        if _is_test_path(item.source_file):
            continue
        if _I18N_PATH.search("/" + item.source_file):
            locale_files.append(item)
        if _I18N_CODE.search(item.text):
            call_files.append(item)
    if not locale_files and not call_files:
        return _finish(
            number, text, "missing", "",
            "未检索到国际化实现：没有语言包、i18n 初始化或翻译函数调用",
            [], [],
        )
    omissions = _locale_omissions(locale_files) + _hardcoded_ui_omissions(files)
    languages = {_language_of(item.source_file) for item in locale_files}
    languages.discard("")
    evidence_pool = [item for item in locale_files if _language_of(item.source_file)] or locale_files or call_files
    evidence = evidence_pool[0].source_file
    note = (
        f"代码里已有国际化：语言包 {len(locale_files)} 个，"
        f"语言 {len(languages)} 种，翻译调用 {len(call_files)} 个文件。"
    )
    if omissions:
        note += f"发现 {len(omissions[:_MAX_I18N_OMISSIONS])} 个国际化问题，见补测用例。"
        verdict = "partial"
    else:
        verdict = "implemented"
    return _finish(number, text, verdict, evidence, note, omissions[:_MAX_I18N_OMISSIONS], [])


def _locale_omissions(locale_files: list[IndexedFile]) -> list[Omission]:
    grouped = {}
    for item in locale_files:
        lang = _language_of(item.source_file)
        if not lang:
            continue
        resource = _resource_name(item.source_file, lang)
        grouped.setdefault(resource, {})[lang] = item
    languages = {lang for langs in grouped.values() for lang in langs}
    if len(languages) <= 1 and locale_files:
        sample = locale_files[0]
        label = _LANG_LABEL.get(_language_of(sample.source_file), "其他语言")
        return [Omission(
            kind="i18n",
            gap=f"只找到 {label} 文案，没有其他语言的对照语言包",
            precondition="系统声称支持切换语言",
            steps="查看语言切换入口，并切换到另一种语言",
            expected="应存在成对的语言包，切换后界面文案跟着变化",
            path=sample.source_file,
        )]
    omissions = []
    for langs in grouped.values():
        if len(omissions) >= 6:
            break
        present_langs = set(langs)
        for lang, item in langs.items():
            keys = _message_keys(item)
            empty = _empty_message_keys(item)
            if empty and len(omissions) < 6:
                shown = "、".join(empty[:5])
                omissions.append(Omission(
                    kind="i18n",
                    gap=f"{_lang_label(lang)} 语言包有空文案：{shown}",
                    precondition=f"系统可切换到{_lang_label(lang)}",
                    steps=f"切换到{_lang_label(lang)}，查看这些键对应的界面",
                    expected="应显示该语言的文案，不应为空白",
                    path=item.source_file,
                ))
            for other in sorted(languages - present_langs):
                if len(omissions) >= 6:
                    break
                omissions.append(Omission(
                    kind="i18n",
                    gap=f"{_lang_label(other)} 没有与 {item.source_file} 对应的语言包",
                    precondition=f"系统可切换到{_lang_label(other)}",
                    steps=f"切换到{_lang_label(other)}，打开该语言包负责的页面",
                    expected="应有对应语言包，文案不应回退成键名或另一种语言",
                    path=item.source_file,
                ))
            for other, other_item in langs.items():
                if other == lang or len(omissions) >= 6:
                    continue
                missing = sorted(keys - _message_keys(other_item))
                if not missing:
                    continue
                shown = "、".join(missing[:5])
                extra = f"等 {len(missing)} 个" if len(missing) > 5 else shown
                detail = extra if len(missing) > 5 else shown
                omissions.append(Omission(
                    kind="i18n",
                    gap=f"{_lang_label(other)} 缺少 {_lang_label(lang)} 已有的键：{detail}",
                    precondition=f"系统可切换到{_lang_label(other)}",
                    steps=f"切换到{_lang_label(other)}，查看这些键对应的界面",
                    expected="应显示该语言的文案，不应出现键名、空白或另一种语言",
                    path=other_item.source_file,
                ))
    return omissions


def _hardcoded_ui_omissions(files: list[IndexedFile]) -> list[Omission]:
    hits = []
    for item in files:
        if Path(item.source_file).suffix.lower() not in _UI_SUFFIXES:
            continue
        if _is_test_path(item.source_file) or _I18N_PATH.search("/" + item.source_file):
            continue
        sample = ""
        count = 0
        for line in item.text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(("//", "/*", "*", "<!--")):
                continue
            if not re.search(r"[\u4e00-\u9fff]", stripped):
                continue
            if _I18N_CALL.search(stripped):
                continue
            count += 1
            if not sample:
                sample = stripped[:40]
        if count:
            hits.append((count, item.source_file, sample))
    hits.sort(key=lambda item: (-item[0], item[1]))
    omissions = []
    for _count, path, sample in hits[:5]:
        omissions.append(Omission(
            kind="i18n",
            gap=f"{path} 有未走翻译函数的中文，例如「{sample}」",
            precondition="系统可切换到非中文语言",
            steps="切换到英文或其他语言，打开该页面",
            expected="该处文字应随语言切换，不应固定显示中文",
            path=path,
        ))
    return omissions


def _language_of(path: str) -> str:
    for part in path.lower().replace("\\", "/").split("/"):
        if part in _LANG_NAMES:
            return part
    return ""


def _resource_name(path: str, lang: str) -> str:
    kept = []
    removed = False
    for part in path.replace("\\", "/").split("/"):
        if not removed and part.lower() == lang:
            removed = True
            continue
        kept.append(part)
    return "/".join(kept)


def _lang_label(lang: str) -> str:
    return _LANG_LABEL.get(lang, lang or "其他语言")


def _message_keys(item: IndexedFile) -> set[str]:
    suffix = Path(item.source_file).suffix.lower()
    if suffix == ".json":
        try:
            payload = json.loads(item.text)
        except json.JSONDecodeError:
            return set()
        return set(_flatten_keys(payload))
    return {key for key in _JS_KEY.findall(item.text) if key not in _JS_KEY_SKIP}


def _empty_message_keys(item: IndexedFile) -> list[str]:
    return list(dict.fromkeys(_EMPTY_I18N_VALUE.findall(item.text)))


def _flatten_keys(value, prefix: str = "") -> list[str]:
    if not isinstance(value, dict):
        return []
    keys = []
    for key, child in value.items():
        full = f"{prefix}.{key}" if prefix else str(key)
        keys.append(full)
        keys.extend(_flatten_keys(child, full))
    return keys


def _judge_user(text: str, snippets: list[FileChunk], surface: str = "mixed") -> str:
    note = ""
    if surface == "backend":
        note = "\n\n当前是后端代码。不要把页面展示、颜色、文案、跳转写成遗漏。"
    return f"需求点：{text}\n\n代码片段：\n{render_batch(snippets)}{note}"


def _score(item: IndexedFile, tokens: list[str]) -> int:
    path = item.source_file.lower()
    symbols = item.symbols.lower()
    text = item.text.lower()
    score = 0
    for token in tokens:
        needle = token.lower()
        if needle in path:
            score += 3
        if needle in symbols:
            score += 4
        count = text.count(needle)
        if count:
            score += min(count, 5)
    return score


def _window(text: str, tokens: list[str], limit: int) -> str:
    lines = text.splitlines()
    if not lines:
        return ""
    needles = [token.lower() for token in tokens]
    hit = 0
    for index, line in enumerate(lines):
        folded = line.lower()
        if any(needle in folded for needle in needles):
            hit = index
            break
    start = max(0, hit - 20)
    end = min(len(lines), hit + 60)
    return "\n".join(lines[start:end])[:limit]


def _is_test_path(path: str) -> bool:
    parts = path.lower().replace("\\", "/").split("/")
    if any(part in {"test", "tests", "__tests__", "spec"} for part in parts):
        return True
    name = parts[-1] if parts else ""
    return ".spec." in name or ".test." in name or name.startswith("test_")


def _match_file(reported: str, known: list[str]) -> str:
    text = (reported or "").replace("\\", "/").strip()
    if text in known:
        return text
    hits = [name for name in known if text and (name.endswith("/" + text) or name.endswith(text))]
    if len(hits) == 1:
        return hits[0]
    return ""


def _as_bool(value, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "是"}
    return bool(value)


def _as_steps(value) -> str:
    if isinstance(value, list):
        return "；".join(str(part).strip() for part in value if str(part).strip())
    return str(value or "").strip()


def _progress(on_progress, value: int) -> None:
    if on_progress:
        on_progress(value)


def _call_json(config, system: str, user: str, expect: str):
    last_error = None
    for _ in range(2):
        try:
            payload = _load_json(call_model(config, system, user))
        except Exception as exc:
            last_error = exc
            continue
        if expect == "list" and isinstance(payload, list):
            return payload
        if expect == "dict" and isinstance(payload, dict):
            return payload
        last_error = ValueError("模型返回的内容不是合法 JSON")
    raise ModelCallError(f"模型调用失败: {last_error}")


def _load_json(raw: str):
    text = _strip_model_wrapper(raw)
    candidates = []
    for item in (text, _relax_json(text), _first_json_array(text), _first_json_object(text)):
        if item and item not in candidates:
            candidates.append(item)
            relaxed = _relax_json(item)
            if relaxed not in candidates:
                candidates.append(relaxed)
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise ValueError("模型返回的内容不是合法 JSON")


def _first_json_object(text: str) -> str:
    start = None
    depth = 0
    in_string = False
    escape = False
    for index, char in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                return text[start:index + 1]
    return ""

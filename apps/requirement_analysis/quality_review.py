"""审查需求正文的完整性、一致性、可测性。"""

import asyncio
import json
import re

REVIEW_TIMEOUT_SECONDS = 90
MAX_FINDINGS = 30
MIN_TEXT_CHARS = 20
MAX_TEXT_CHARS = 30000

_DIMENSIONS = {"completeness", "consistency", "testability"}
_ISSUE_TYPES = {"missing", "ambiguity", "conflict", "untestable"}
_SEVERITIES = {"high", "medium", "low"}
_DIMENSION_ALIAS = {
    "completeness": "completeness",
    "完整性": "completeness",
    "consistency": "consistency",
    "一致性": "consistency",
    "testability": "testability",
    "可测性": "testability",
}
_ISSUE_ALIAS = {
    "missing": "missing",
    "缺失": "missing",
    "ambiguity": "ambiguity",
    "歧义": "ambiguity",
    "conflict": "conflict",
    "冲突": "conflict",
    "untestable": "untestable",
    "不可测": "untestable",
}
_SEVERITY_ALIAS = {
    "high": "high",
    "高": "high",
    "medium": "medium",
    "中": "medium",
    "low": "low",
    "低": "low",
}
_DEFAULT_ISSUE = {
    "completeness": "missing",
    "consistency": "conflict",
    "testability": "untestable",
}
_PENALTY = {"high": 25, "medium": 12, "low": 5}
_SCORE_CAP = {"high": 59, "medium": 79}
_SCORE_KEYS = {
    "completeness": "completeness_score",
    "consistency": "consistency_score",
    "testability": "testability_score",
}

SYSTEM_PROMPT = """你是需求评审专家。审查需求正文的完整性、一致性、可测性，把缺陷拦在评审阶段。

只输出一个 JSON 对象，不要 Markdown，不要解释。

字段：
- completeness_score: 0到100的整数。角色、前置、输入输出、异常、边界、状态变化、权限、验收标准是否写全。
- consistency_score: 0到100的整数。术语、规则、数量、状态是否前后一致。
- testability_score: 0到100的整数。能否据此写出可执行步骤和可观察的预期。
- summary: 字符串。给评审人的三五句话，说明能不能进入用例设计。
- findings: 数组。没有问题时为空数组。每项：
  - dimension: completeness、consistency、testability 之一
  - issue_type: missing、ambiguity、conflict、untestable 之一
  - severity: high、medium、low 之一
    high: 不改就无法设计或实现
    medium: 不改会让测试和实现各做各的
    low: 可以更清楚，但不阻塞
  - location: 字符串。章节或条目，看不出则写「全文」
  - quote: 字符串。有问题的原文，不超过80字。缺失且没有原文时用空字符串
  - problem: 字符串。缺了什么、哪里歧义、和哪一条冲突、为什么测不了
  - suggestion: 字符串。可直接补进需求的改法，写明条件和预期

规则：
1. 只根据给定需求，不要编造文档里没有的业务。
2. 一条 finding 只写一个问题。
3. 完整性问题用 missing。一致性问题用 conflict。说不清、无法观察结果用 ambiguity 或 untestable。
4. 已经写清楚的内容不要报问题。
5. 不要输出测试用例。
6. 最多 30 条，优先 high 和 medium。
7. 没有可审查的正文时，三个分数都给 0，findings 为空数组，summary 说明原因。"""


class QualityReviewError(Exception):
    pass


def prepare_text(text: str) -> tuple[str, bool]:
    cleaned = (text or "").strip()
    if cleaned.startswith((
        "PDF文本提取失败",
        "Word文档文本提取失败",
        "文本文件读取失败",
        "不支持的文档类型",
    )):
        raise QualityReviewError(cleaned)
    if len(cleaned) < MIN_TEXT_CHARS:
        raise QualityReviewError("需求内容过短，至少需要 20 个字才能审查")
    truncated = len(cleaned) > MAX_TEXT_CHARS
    return cleaned[:MAX_TEXT_CHARS], truncated


def parse_model_payload(raw: str) -> dict:
    text = (raw or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise QualityReviewError("模型没有返回审查结果")
    blob = re.sub(r",\s*([}\]])", r"\1", text[start:end + 1])
    try:
        data = json.loads(blob)
    except json.JSONDecodeError as exc:
        raise QualityReviewError("模型返回的审查结果无法解析") from exc
    if not isinstance(data, dict):
        raise QualityReviewError("模型返回的审查结果无法解析")
    return data


def normalize_review(data: dict) -> dict:
    findings = _findings(data.get("findings"))
    scores = {
        dimension: _dimension_score(dimension, findings, _score(data.get(key)))
        for dimension, key in _SCORE_KEYS.items()
    }
    verdict = _verdict(findings, scores)
    summary = str(data.get("summary") or "").strip()
    if not summary:
        summary = _default_summary(verdict)
    return {
        "verdict": verdict,
        "completeness_score": scores["completeness"],
        "consistency_score": scores["consistency"],
        "testability_score": scores["testability"],
        "overall_score": round(sum(scores.values()) / 3),
        "summary": summary[:2000],
        "findings": findings,
    }


def review_requirement(config, text: str, title: str) -> dict:
    last_error = None
    for _ in range(2):
        raw = _call_model(config, text, title)
        try:
            return normalize_review(parse_model_payload(raw))
        except QualityReviewError as exc:
            last_error = exc
    raise last_error


def _call_model(config, text: str, title: str) -> str:
    from apps.requirement_analysis.models import AIModelService

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"标题：{title}\n\n需求正文：\n{text}"},
    ]

    async def _limited():
        return await asyncio.wait_for(
            AIModelService.call_openai_compatible_api(config, messages, max_tokens=4096),
            timeout=REVIEW_TIMEOUT_SECONDS,
        )

    try:
        result = asyncio.run(_limited())
    except TimeoutError:
        raise QualityReviewError("模型审查超时，请缩短需求后再试") from None
    except Exception as exc:
        message = str(exc).strip() or "模型调用失败"
        raise QualityReviewError(message[:300]) from exc

    choice = (result.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = str(message.get("content") or message.get("reasoning_content") or "").strip()
    if not content:
        raise QualityReviewError("模型没有返回审查结果")
    return content


def _findings(raw) -> list[dict]:
    if not isinstance(raw, list):
        return []
    findings = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        finding = _one_finding(item)
        if finding is None:
            continue
        key = (finding["dimension"], finding["quote"], finding["problem"])
        if key in seen:
            continue
        seen.add(key)
        findings.append(finding)
        if len(findings) >= MAX_FINDINGS:
            break
    for index, finding in enumerate(findings, start=1):
        finding["id"] = f"F{index}"
    return findings


def _one_finding(item: dict) -> dict | None:
    dimension = _DIMENSION_ALIAS.get(str(item.get("dimension") or "").strip().lower(), "")
    if not dimension:
        dimension = _DIMENSION_ALIAS.get(str(item.get("dimension") or "").strip(), "")
    if dimension not in _DIMENSIONS:
        return None
    problem = _clip(item.get("problem"), 400)
    if not problem:
        return None
    issue_type = _ISSUE_ALIAS.get(str(item.get("issue_type") or "").strip().lower(), "")
    if not issue_type:
        issue_type = _ISSUE_ALIAS.get(str(item.get("issue_type") or "").strip(), "")
    if issue_type not in _ISSUE_TYPES:
        issue_type = _DEFAULT_ISSUE[dimension]
    severity = _SEVERITY_ALIAS.get(str(item.get("severity") or "").strip().lower(), "")
    if not severity:
        severity = _SEVERITY_ALIAS.get(str(item.get("severity") or "").strip(), "")
    if severity not in _SEVERITIES:
        severity = "medium"
    location = _clip(item.get("location"), 120) or "全文"
    return {
        "dimension": dimension,
        "issue_type": issue_type,
        "severity": severity,
        "location": location,
        "quote": _clip(item.get("quote"), 80),
        "problem": problem,
        "suggestion": _clip(item.get("suggestion"), 400),
        "blocks_test": severity == "high",
    }


def _dimension_score(dimension: str, findings: list[dict], given: int | None) -> int:
    related = [item for item in findings if item["dimension"] == dimension]
    if given is None:
        score = 100
        for item in related:
            score -= _PENALTY[item["severity"]]
        score = max(score, 0)
    else:
        score = given
    if any(item["severity"] == "high" for item in related):
        return min(score, _SCORE_CAP["high"])
    if any(item["severity"] == "medium" for item in related):
        return min(score, _SCORE_CAP["medium"])
    return score


def _verdict(findings: list[dict], scores: dict[str, int]) -> str:
    severities = {item["severity"] for item in findings}
    if "high" in severities:
        return "block"
    if "medium" in severities or any(score <= 59 for score in scores.values()):
        return "revise"
    return "pass"


def _default_summary(verdict: str) -> str:
    if verdict == "block":
        return "存在必须先改掉的需求缺陷，暂不进入用例设计。"
    if verdict == "revise":
        return "存在需要改清楚的需求问题，修改后再进入用例设计。"
    return "未发现需要拦截的需求缺陷，可以进入用例设计。"


def _score(value) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    return max(0, min(100, number))


def _clip(value, limit: int) -> str:
    return str(value or "").strip()[:limit]

"""把口头或散乱输入整理成结构化需求文档和验收标准。"""

import asyncio
import json
import re

WRITE_TIMEOUT_SECONDS = 90
WRITE_TEMPERATURE = 0.2
MIN_TEXT_CHARS = 20
MAX_TEXT_CHARS = 30000
MAX_SECTION_CHARS = 3000
MAX_CRITERIA = 30
MAX_QUESTIONS = 20
FIELD_CHARS = 400

EMPTY_MARK = "（输入未说明）"
SECTION_ORDER = (
    ("background", "背景与目标"),
    ("roles", "角色与权限"),
    ("preconditions", "前置条件"),
    ("main_flow", "主流程"),
    ("exceptions", "异常与边界"),
    ("state_changes", "状态变化"),
    ("inputs_outputs", "输入输出"),
)
_SECTION_ALIAS = {
    "background": "background",
    "背景与目标": "background",
    "背景": "background",
    "roles": "roles",
    "角色与权限": "roles",
    "角色": "roles",
    "preconditions": "preconditions",
    "前置条件": "preconditions",
    "前置": "preconditions",
    "main_flow": "main_flow",
    "主流程": "main_flow",
    "exceptions": "exceptions",
    "异常与边界": "exceptions",
    "异常": "exceptions",
    "state_changes": "state_changes",
    "状态变化": "state_changes",
    "状态": "state_changes",
    "inputs_outputs": "inputs_outputs",
    "输入输出": "inputs_outputs",
}

SYSTEM_PROMPT = """你是需求分析员。把口头说明、会议纪要或散乱笔记整理成一份可评审的需求文档。

只输出一个 JSON 对象，不要 Markdown，不要解释。

字段：
- sections: 对象，键只能是 background、roles、preconditions、main_flow、exceptions、state_changes、inputs_outputs。值是字符串。
  background 背景与目标，roles 角色与权限，preconditions 前置条件，main_flow 主流程，exceptions 异常与边界，state_changes 状态变化，inputs_outputs 输入输出。
- acceptance_criteria: 数组。每项有 condition、action、expected 三个字符串，分别是条件、操作、可观察结果。
- open_questions: 数组。每项有 topic、missing、impact 三个字符串，分别是主题、输入里缺了什么、为什么不补上就写不出可判定的验收标准。

规则：
1. 只整理输入里已经写明的事实。不要补充输入里没有的业务规则、数字、时限、权限、错误码、状态或接口。
2. 某一节在输入里没有信息时，这一节只写「（输入未说明）」，并在 open_questions 里说明缺什么。
3. 验收标准只收录输入已经能同时支持条件、操作和可观察结果的条目。三者缺任何一个，就不要放进 acceptance_criteria，改写入 open_questions。
4. 同一概念只用输入里的同一个词，不要另起名称。
5. 不要输出测试用例。
6. 没有可整理的内容时，七个章节都写「（输入未说明）」，两个数组都为空数组。"""


class RequirementWriteError(Exception):
    pass


def prepare_source(text: str) -> tuple[str, bool]:
    cleaned = (text or "").strip()
    if len(cleaned) < MIN_TEXT_CHARS:
        raise RequirementWriteError("输入过短，至少需要 20 个字才能整理")
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
        raise RequirementWriteError("模型没有返回需求文档")
    blob = re.sub(r",\s*([}\]])", r"\1", text[start:end + 1])
    try:
        data = json.loads(blob)
    except json.JSONDecodeError as exc:
        raise RequirementWriteError("模型返回的需求文档无法解析") from exc
    if not isinstance(data, dict):
        raise RequirementWriteError("模型返回的需求文档无法解析")
    return data


def normalize_draft(data: dict, title: str) -> dict:
    sections = _sections(data)
    criteria = _criteria(data.get("acceptance_criteria") or data.get("验收标准"))
    questions = _questions(data.get("open_questions") or data.get("待确认"))
    questions = _drop_incomplete_criteria(criteria, questions)
    criteria = [item for item in criteria if item.pop("_keep", True)]
    for index, item in enumerate(criteria, start=1):
        item["id"] = f"A{index}"
    for index, item in enumerate(questions, start=1):
        item["id"] = f"Q{index}"
    unspecified = [label for key, label in SECTION_ORDER if sections[key] == EMPTY_MARK]
    return {
        "sections": sections,
        "acceptance_criteria": criteria,
        "open_questions": questions,
        "gaps_unlisted": bool(unspecified) and not questions,
        "document_markdown": render_markdown(title, sections, criteria, questions),
    }


def render_markdown(title: str, sections: dict, criteria: list, questions: list) -> str:
    lines = [f"# {title}", ""]
    for key, label in SECTION_ORDER:
        lines.extend([f"## {label}", sections.get(key) or EMPTY_MARK, ""])
    lines.append("## 验收标准")
    if criteria:
        for index, item in enumerate(criteria, start=1):
            lines.append(
                f"{index}. 条件：{item['condition']}；操作：{item['action']}；预期：{item['expected']}"
            )
    else:
        lines.append(EMPTY_MARK)
    lines.append("")
    lines.append("## 待确认")
    if questions:
        for index, item in enumerate(questions, start=1):
            detail = item["missing"]
            if item["impact"]:
                detail = f"{detail}。{item['impact']}" if detail else item["impact"]
            lines.append(f"{index}. {item['topic']}：{detail}")
    else:
        lines.append("输入中未发现需要单列的待确认项。")
    return "\n".join(lines).strip() + "\n"


def write_requirement(config, text: str, title: str) -> dict:
    last_error = None
    for _ in range(2):
        raw = _call_model(config, text, title)
        try:
            return normalize_draft(parse_model_payload(raw), title)
        except RequirementWriteError as exc:
            last_error = exc
    raise last_error


def _call_model(config, text: str, title: str) -> str:
    from apps.requirement_analysis.models import AIModelService

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"标题：{title}\n\n原始输入：\n{text}"},
    ]

    async def _limited():
        return await asyncio.wait_for(
            AIModelService.call_openai_compatible_api(
                config,
                messages,
                max_tokens=4096,
                temperature=WRITE_TEMPERATURE,
            ),
            timeout=WRITE_TIMEOUT_SECONDS,
        )

    try:
        result = asyncio.run(_limited())
    except TimeoutError:
        raise RequirementWriteError("模型整理超时，请缩短输入后再试") from None
    except Exception as exc:
        message = str(exc).strip() or "模型调用失败"
        raise RequirementWriteError(message[:300]) from exc

    choice = (result.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = str(message.get("content") or message.get("reasoning_content") or "").strip()
    if not content:
        raise RequirementWriteError("模型没有返回需求文档")
    return content


def _sections(data: dict) -> dict:
    raw = data.get("sections") if isinstance(data.get("sections"), dict) else data
    if not isinstance(raw, dict):
        raw = {}
    found = {}
    for key, value in raw.items():
        name = _SECTION_ALIAS.get(str(key).strip()) or _SECTION_ALIAS.get(str(key).strip().lower())
        if name and name not in found:
            found[name] = _clip(value, MAX_SECTION_CHARS)
    return {key: found.get(key) or EMPTY_MARK for key, _label in SECTION_ORDER}


def _criteria(raw) -> list[dict]:
    if not isinstance(raw, list):
        return []
    items = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        condition = _field(item, "condition", "条件")
        action = _field(item, "action", "操作")
        expected = _field(item, "expected", "预期", "expected_result")
        if not condition and not action and not expected:
            continue
        key = (condition, action, expected)
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "condition": condition,
            "action": action,
            "expected": expected,
            "_keep": bool(condition and action and expected),
        })
        if len(items) >= MAX_CRITERIA:
            break
    return items


def _questions(raw) -> list[dict]:
    if not isinstance(raw, list):
        return []
    items = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        topic = _field(item, "topic", "主题") or "待确认"
        missing = _field(item, "missing", "缺失")
        impact = _field(item, "impact", "影响")
        if not missing and not impact:
            continue
        key = (topic, missing)
        if key in seen:
            continue
        seen.add(key)
        items.append({"topic": topic, "missing": missing, "impact": impact})
        if len(items) >= MAX_QUESTIONS:
            break
    return items


def _drop_incomplete_criteria(criteria: list[dict], questions: list[dict]) -> list[dict]:
    seen = {(item["topic"], item["missing"]) for item in questions}
    for item in criteria:
        if item["_keep"]:
            continue
        topic = item["condition"] or item["action"] or "验收标准"
        missing = "条件、操作或可观察结果没有在输入里写全"
        if (topic, missing) in seen or len(questions) >= MAX_QUESTIONS:
            continue
        seen.add((topic, missing))
        questions.append({
            "topic": topic,
            "missing": missing,
            "impact": "补全后才能作为验收标准。",
        })
    return questions


def _field(item: dict, *names: str) -> str:
    for name in names:
        value = _clip(item.get(name), FIELD_CHARS)
        if value:
            return value
    return ""


def _clip(value, limit: int) -> str:
    return str(value or "").strip()[:limit]

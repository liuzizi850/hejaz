"""根据入参结构导出字段说明。只写出代码里能看出的类型、必填、长度和枚举。"""

import json
import re

from apps.code_monitor.sample_data import (
    _ARRAY_KINDS,
    _BOOL_KINDS,
    _FLOAT_KINDS,
    _INT_KINDS,
    _OBJECT_KINDS,
    _STRING_KINDS,
    _is_layer_object,
    _is_type_token,
    _parse_hint,
)

_MAX_FIELDS = 40
_MAX_DEPTH = 8
_MAX_LENGTH = re.compile(r"(?:maxLength|maxLen|最大长度)\s*[=:：]?\s*(\d+)", re.I)
_ENUM_NOISE = re.compile(
    r"^(?:"
    r"(?:string|str|text|varchar|char|number|int|integer|long|float|double|decimal|boolean|bool|array|list|object|date|datetime|time)\b\s*[,，:：]\s*"
    r"|(?:required|optional|unique)\b\s*[,，:：]\s*"
    r"|(?:非必填|必填|可选|必须|非空|唯一)\s*[,，:：]\s*"
    r"|(?:maxLength|maxLen|minLength|minLen|最大长度|最小长度|最小值|最大值|min|max)\s*[=:：]?\s*-?\d+(?:\.\d+)?\s*[,，]?\s*"
    r")",
    re.I,
)
_TYPE_NAMES = {
    "string": "字符串",
    "number": "数字",
    "boolean": "布尔",
    "array": "数组",
    "object": "对象",
    "date": "日期",
    "datetime": "日期时间",
    "time": "时间",
}


def render_test_points(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return ""
    if not isinstance(parsed, (dict, list)):
        return ""
    fields = []
    skipped = [0]
    _collect(parsed, "", fields, skipped)
    if not fields:
        return ""
    blocks = [_render_field(field) for field in fields]
    if skipped[0]:
        blocks.append(f"其余 {skipped[0]} 个字段同样列出必填、长度、类型和枚举")
    return "\n\n".join(block for block in blocks if block)


def _keep(fields: list, skipped: list, field: dict):
    if len(fields) < _MAX_FIELDS:
        fields.append(field)
        return
    skipped[0] += 1


def _collect(value, path: str, fields: list, skipped: list, depth: int = 0):
    if depth > _MAX_DEPTH:
        return
    if isinstance(value, dict) and not path and _is_layer_object(value):
        for layer in ("query", "body"):
            item = value.get(layer)
            if item in ({}, [], "", None):
                continue
            _collect(item, layer, fields, skipped, depth + 1)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}" if path else str(key)
            if isinstance(item, dict):
                if item:
                    _collect(item, child, fields, skipped, depth + 1)
                else:
                    _keep(fields, skipped, _make_field(child, "object", "", ""))
            elif isinstance(item, list):
                _collect_list(item, child, fields, skipped, depth + 1)
            else:
                _keep(fields, skipped, _field_from_value(child, item))
        return
    if isinstance(value, list):
        _collect_list(value, path or "body", fields, skipped, depth + 1)


def _collect_list(items, path: str, fields: list, skipped: list, depth: int):
    if items and all(isinstance(item, str) and not _is_type_token(item) for item in items):
        _keep(fields, skipped, _make_field(path, "string", "", "|".join(str(item) for item in items)))
        return
    item_kind = ""
    if items and isinstance(items[0], str):
        hint = _parse_hint(items[0])
        if hint:
            item_kind = hint[0]
    _keep(fields, skipped, _make_field(path, "array", item_kind, ""))
    if items and isinstance(items[0], dict):
        _collect(items[0], f"{path}[]", fields, skipped, depth + 1)


def _field_from_value(path: str, value):
    if isinstance(value, bool):
        return _make_field(path, "bool", "", "")
    if isinstance(value, int):
        return _make_field(path, "int", "", "")
    if isinstance(value, float):
        return _make_field(path, "float", "", "")
    if isinstance(value, str):
        hint = _parse_hint(value.strip())
        if hint:
            return _make_field(path, hint[0], hint[1], hint[2])
        return _make_field(path, "string", "", value.strip())
    return _make_field(path, "string", "", "")


def _make_field(path: str, kind: str, item_kind: str, note: str):
    return {
        "path": path,
        "key": path.rsplit(".", 1)[-1].removesuffix("[]"),
        "kind": (kind or "string").lower(),
        "item_kind": (item_kind or "").lower(),
        "note": note or "",
    }


def _render_field(field: dict) -> str:
    kind = _kind_label(field["kind"])
    note = field["note"]
    enums = _enums(note)
    required = "是" if _required_flag(note) is True else "否"
    enum_text = f"是【{'、'.join(enums)}】" if len(enums) >= 2 else "否"
    return "\n".join([
        f"{field['path']}（{kind}）",
        f"必填：{required}",
        f"长度：{_length_text(note)}",
        f"参数类型：{_type_text(kind, field['item_kind'])}",
        f"枚举值：{enum_text}",
    ])


def _type_text(kind: str, item_kind: str) -> str:
    if kind == "array" and item_kind:
        item = _kind_label(item_kind)
        return f"array({_TYPE_NAMES.get(item, item)}数组)"
    return f"{kind}({_TYPE_NAMES.get(kind, kind)})"


def _length_text(note: str) -> str:
    match = _MAX_LENGTH.search(note or "")
    if not match:
        return "-"
    return match.group(1)


def _kind_label(kind: str) -> str:
    if kind in _INT_KINDS or kind in _FLOAT_KINDS:
        return "number"
    if kind in _BOOL_KINDS:
        return "boolean"
    if kind in _ARRAY_KINDS:
        return "array"
    if kind in _OBJECT_KINDS:
        return "object"
    if kind in _STRING_KINDS:
        return "string"
    return kind or "string"


def _required_flag(note: str):
    text = _constraint_note(note)
    if re.search(r"非必填|可选|optional", text, flags=re.I):
        return False
    if re.search(r"(?<!非)必填|必须|(?<![A-Za-z])required|非空", text, flags=re.I):
        return True
    return None


def _constraint_note(note: str) -> str:
    text = note or ""
    if "|" not in text:
        return text
    head = text.split("|", 1)[0]
    bits = re.split(r"\s*[,，]\s*", head)
    if len(bits) <= 1:
        return ""
    return ",".join(bits[:-1])


def _enums(note: str) -> list[str]:
    text = note or ""
    if "|" not in text:
        return []
    parts = []
    for part in text.split("|"):
        cleaned = _clean_enum_part(part)
        if cleaned:
            parts.append(cleaned)
    return parts if len(parts) >= 2 else []


def _clean_enum_part(part: str) -> str:
    text = part.strip()
    previous = None
    while text and text != previous:
        previous = text
        text = _ENUM_NOISE.sub("", text, count=1).strip()
    return text.strip(" ,，:：")

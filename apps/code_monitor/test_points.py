"""根据入参结构标出可执行的测试要点。只覆盖代码里能看出的字段和约束。"""

import json
import re

from apps.code_monitor.sample_data import (
    _ARRAY_KINDS,
    _BOOL_KINDS,
    _ENUM_SEARCH,
    _FLOAT_KINDS,
    _INT_KINDS,
    _OBJECT_KINDS,
    _STRING_KINDS,
    _is_layer_object,
    _parse_hint,
    _sample_scalar,
)

_MAX_FIELDS = 40
_MAX_DEPTH = 8
_MAX_LENGTH = re.compile(r"(?:maxLength|maxLen|最大长度)\s*[=:：]?\s*(\d+)", re.I)
_MIN_VALUE = re.compile(r"(?:(?<![A-Za-z])min|最小值)\s*[=:：]?\s*(-?\d+(?:\.\d+)?)", re.I)
_MAX_VALUE = re.compile(r"(?:(?<![A-Za-z])max|最大值)\s*[=:：]?\s*(-?\d+(?:\.\d+)?)", re.I)


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
    _collect(parsed, "", fields)
    if not fields:
        return ""
    blocks = [_render_field(field) for field in fields[:_MAX_FIELDS]]
    hidden = len(fields) - _MAX_FIELDS
    if hidden > 0:
        blocks.append(f"其余 {hidden} 个字段同样检查必填、类型、枚举和边界")
    return "\n\n".join(block for block in blocks if block)


def _collect(value, path: str, fields: list, depth: int = 0):
    if depth > _MAX_DEPTH or len(fields) >= _MAX_FIELDS:
        return
    if isinstance(value, dict) and not path and _is_layer_object(value):
        for layer in ("query", "body"):
            item = value.get(layer)
            if item in ({}, [], "", None):
                continue
            _collect(item, layer, fields, depth + 1)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}" if path else str(key)
            if isinstance(item, dict):
                if item:
                    _collect(item, child, fields, depth + 1)
                else:
                    fields.append(_make_field(child, "object", "", ""))
            elif isinstance(item, list):
                _collect_list(item, child, fields, depth + 1)
            else:
                fields.append(_field_from_value(child, item))
        return
    if isinstance(value, list):
        _collect_list(value, path or "body", fields, depth + 1)


def _collect_list(items, path: str, fields: list, depth: int):
    if len(fields) >= _MAX_FIELDS:
        return
    if items and all(isinstance(item, str) and _parse_hint(item) is None for item in items):
        fields.append(_make_field(path, "string", "", "|".join(str(item) for item in items)))
        return
    item_kind = ""
    if items and isinstance(items[0], str):
        hint = _parse_hint(items[0])
        if hint:
            item_kind = hint[0]
    fields.append(_make_field(path, "array", item_kind, ""))
    if items and isinstance(items[0], dict):
        _collect(items[0], f"{path}[]", fields, depth + 1)


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
    kind = field["kind"]
    note = field["note"]
    enums = _enums(note)
    required = _required_flag(note)
    lines = [_title(field, enums, required)]
    if required is True:
        lines.append("必填参数：不传、传空字符串、null")
    elif required is False:
        lines.append(f"参数可选字段：不传、传 null、传有效值 {_valid_text(field)}")
    else:
        lines.append("必填参数：不传、传空字符串、null")
        lines.append(f"参数可选字段：不传、传 null、传有效值 {_valid_text(field)}")
    if len(enums) >= 2:
        lines.append(f"参数枚举值：合法枚举 {'、'.join(enums)}；不在枚举里的值 NOT_A_VALUE")
    type_line = _type_line(kind)
    if type_line:
        lines.append(type_line)
    boundary = _boundary_line(kind, note, field["item_kind"])
    if boundary:
        lines.append(boundary)
    unique = _unique_line(field["key"], note)
    if unique:
        lines.append(unique)
    state = _state_line(field["key"], note, enums)
    if state:
        lines.append(state)
    return "\n".join(lines)


def _title(field: dict, enums: list[str], required) -> str:
    tags = [_kind_label(field["kind"])]
    if required is True:
        tags.append("必填")
    elif required is False:
        tags.append("可选")
    if len(enums) >= 2:
        tags.append("枚举 " + "|".join(enums))
    if _unique_line(field["key"], field["note"]):
        tags.append("唯一")
    return f"{field['path']}（{'，'.join(tags)}）"


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
    if re.search(r"非必填|可选|optional", note, flags=re.I):
        return False
    if re.search(r"(?<!非)必填|必须|(?<![A-Za-z])required|非空", note, flags=re.I):
        return True
    return None


def _enums(note: str) -> list[str]:
    match = _ENUM_SEARCH.search(note or "")
    if match:
        return [part.strip() for part in match.group(0).split("|") if part.strip()]
    if "|" not in (note or ""):
        return []
    parts = []
    for part in note.split("|"):
        cleaned = re.sub(
            r"^(?:string|number|int|integer|boolean|bool)\b\s*[,，:：]?\s*",
            "",
            part.strip(),
            flags=re.I,
        ).strip()
        cleaned = re.sub(r"\b(?:required|optional|unique)\b\s*[,，:：]?\s*", "", cleaned, flags=re.I).strip()
        if cleaned:
            parts.append(cleaned)
    return parts if len(parts) >= 2 else []


def _valid_text(field: dict) -> str:
    enums = _enums(field["note"])
    if enums:
        return enums[0]
    value = _sample_scalar(field["kind"], field["key"], field["note"])
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _type_line(kind: str) -> str:
    if kind in _INT_KINDS or kind in _FLOAT_KINDS:
        return '参数类型：数字传字符串 "1"'
    if kind in _BOOL_KINDS:
        return "参数类型：布尔传 0、传 1"
    if kind in _ARRAY_KINDS:
        return "参数类型：数组传对象 {}"
    if kind in _OBJECT_KINDS:
        return "参数类型：对象传数组 []"
    if kind in _STRING_KINDS or kind in {"date", "datetime", "time"}:
        return "参数类型：字符串传数字 1"
    return ""


def _boundary_line(kind: str, note: str, item_kind: str = "") -> str:
    length_note = _MAX_LENGTH.sub("", note or "")
    length_match = _MAX_LENGTH.search(note or "")
    min_match = _MIN_VALUE.search(length_note)
    max_match = _MAX_VALUE.search(length_note)
    parts = []
    if min_match and max_match and kind not in _STRING_KINDS:
        lower = _as_number(min_match.group(1))
        upper = _as_number(max_match.group(1))
        parts.append(
            f"最小值 {lower}、最大值 {upper}、刚好临界 {lower} 和 {upper}、"
            f"超出上限 {_step(upper, 1)}、低于下限 {_step(lower, -1)}"
        )
    elif min_match and kind not in _STRING_KINDS:
        lower = _as_number(min_match.group(1))
        parts.append(f"最小值 {lower}、刚好临界 {lower}、低于下限 {_step(lower, -1)}")
    elif max_match and kind not in _STRING_KINDS:
        upper = _as_number(max_match.group(1))
        parts.append(f"最大值 {upper}、刚好临界 {upper}、超出上限 {_step(upper, 1)}")
    elif kind in _INT_KINDS or kind in _FLOAT_KINDS:
        parts.append("代码未标明上下限，建议测 0、负数、很大的数")
    if kind in _STRING_KINDS or item_kind in _STRING_KINDS:
        if length_match:
            size = int(length_match.group(1))
            parts.append(f"超长字符串，长度刚好 {size}、超出 {size + 1}")
        else:
            parts.append("超长字符串")
    if not parts:
        return ""
    return "边界值：" + "；".join(parts)


def _as_number(text: str):
    number = float(text)
    if number.is_integer():
        return int(number)
    return number


def _step(number, direction: int):
    if isinstance(number, float):
        return round(number + (0.1 * direction), 1)
    return number + direction


def _unique_line(key: str, note: str) -> str:
    norm = re.sub(r"[\s_\-]", "", key).lower()
    if _key_is(norm, ("phone", "mobile", "telephone", "tel")) or "手机" in note:
        return "业务唯一性：唯一键重复提交（用已存在的手机号再提交一次）"
    if _key_is(norm, ("orderno", "ordernum", "outtradeno", "tradeno")) or "订单号" in note:
        return "业务唯一性：唯一键重复提交（用已存在的订单号再提交一次）"
    if _key_is(norm, ("serialno", "flowno", "sequenceno", "transactionno")) or "流水号" in note:
        return "业务唯一性：唯一键重复提交（用已存在的流水号再提交一次）"
    if re.search(r"唯一|unique", note, flags=re.I):
        return "业务唯一性：唯一键重复提交（用已存在的值再提交一次）"
    return ""


def _key_is(norm: str, words: tuple[str, ...]) -> bool:
    for word in words:
        if norm == word or (len(word) >= 5 and norm.endswith(word)):
            return True
    return False


def _state_line(key: str, note: str, enums: list[str]) -> str:
    norm = re.sub(r"[\s_\-]", "", key).lower()
    is_state = norm == "status" or norm.endswith("status") or norm == "state" or norm.endswith("state") or "状态" in note
    blob = f"{note} {' '.join(enums)}"
    refund = any(word in blob.lower() for word in ("已退款", "refunded", "refund"))
    if not is_state and not refund:
        return ""
    if refund:
        return "状态机校验：只能按业务状态流转，禁止逆状态变更（已退款订单不要再发起支付）"
    if enums:
        shown = "、".join(enums[:6])
        return f"状态机校验：只能按 {shown} 正向流转，禁止从终态逆向变更"
    return "状态机校验：只能按业务状态流转，禁止逆状态变更"

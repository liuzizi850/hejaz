"""把接口入参结构转成可直接粘贴的测试数据。"""

import json
import re

_STRING_KINDS = {"string", "str", "text", "varchar", "char", "any"}
_INT_KINDS = {"number", "int", "integer", "long", "num"}
_FLOAT_KINDS = {"float", "double", "decimal"}
_BOOL_KINDS = {"boolean", "bool"}
_OBJECT_KINDS = {"object", "dict", "map", "json"}
_ARRAY_KINDS = {"array", "list"}
_DATE_KINDS = {"date"}
_DATETIME_KINDS = {"datetime", "timestamp"}
_ALL_KINDS = (
    _STRING_KINDS | _INT_KINDS | _FLOAT_KINDS | _BOOL_KINDS
    | _OBJECT_KINDS | _ARRAY_KINDS | _DATE_KINDS | _DATETIME_KINDS
    | {"time", "file", "null"}
)
_LAYER_KEYS = ("query", "body", "headers")
_ENUM_RE = re.compile(r"^[A-Za-z0-9_+\-]+(?:\s*\|\s*[A-Za-z0-9_+\-]+)+$")
_ENUM_SEARCH = re.compile(r"([A-Za-z0-9_+\-]+)(?:\s*\|\s*[A-Za-z0-9_+\-]+)+")
_MAX_DEPTH = 8
_MAX_LIST = 5


def render_request_sample(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return ""
    if not isinstance(parsed, (dict, list)):
        return ""
    converted = _convert(parsed)
    if isinstance(parsed, dict) and _is_layer_object(parsed):
        return _format_layers(converted)
    if converted in ({}, [], "", None):
        return ""
    return _pretty(converted)


def _convert(value, key: str = "", depth: int = 0):
    if depth > _MAX_DEPTH:
        return {} if isinstance(value, (dict, list)) else value
    if isinstance(value, dict):
        return {str(name): _convert(item, str(name), depth + 1) for name, item in value.items()}
    if isinstance(value, list):
        if not value:
            return []
        items = value[:_MAX_LIST]
        if all(isinstance(item, str) and not _is_type_token(item) for item in items):
            return items
        return [_convert(item, key, depth + 1) for item in items]
    if isinstance(value, str):
        stripped = value.strip()
        hint = _parse_hint(stripped)
        if hint is None:
            if _ENUM_RE.fullmatch(stripped):
                return _ENUM_SEARCH.search(stripped).group(1)
            return value
        kind, item_kind, note = hint
        if kind in _ARRAY_KINDS:
            item = item_kind or ("int" if _is_id_key(_norm(key)) else "string")
            return [_sample_scalar(item, key, note)]
        if kind in _OBJECT_KINDS:
            return {}
        if kind == "null":
            return None
        return _sample_scalar(kind, key, note)
    return value


def _is_type_token(text: str) -> bool:
    stripped = text.strip()
    if not re.match(r"^[A-Za-z]", stripped):
        return False
    return _parse_hint(stripped) is not None


def _parse_hint(text: str):
    original = text.strip()
    prefix = re.match(r"^(optional|required)\b\s*[,，:：]?\s*(.*)$", original, flags=re.I)
    if prefix and prefix.group(2).strip():
        kind, item_kind, note = _parse_hint(prefix.group(2).strip())
        flag = prefix.group(1).lower()
        if flag not in note.lower():
            note = f"{flag}, {note}".strip(", ")
        return (kind, item_kind, note)
    cleaned = re.sub(r"\s*\|\s*null\b", "", original, flags=re.I).strip()
    cleaned = re.sub(r"^(optional|required)\s+", "", cleaned, flags=re.I).strip()
    if not cleaned:
        return ("string", "", "")
    array_match = re.fullmatch(r"(?:array|list)\s*[<(]\s*([A-Za-z]+)\s*[>)]", cleaned, flags=re.I)
    if array_match:
        return ("array", array_match.group(1).lower(), "")
    bracket_match = re.fullmatch(r"([A-Za-z]+)\s*\[\s*\]", cleaned)
    if bracket_match:
        return ("array", bracket_match.group(1).lower(), "")
    typed = re.match(r"^([A-Za-z]+)\b\s*(?:[,，:：|\-—]\s*(.*))?$", cleaned)
    if typed and typed.group(1).lower() in _ALL_KINDS:
        return (typed.group(1).lower(), "", (typed.group(2) or "").strip())
    if re.search(r"[\u4e00-\u9fff]", cleaned):
        return (_kind_from_chinese(cleaned), "", cleaned)
    return None


def _kind_from_chinese(text: str) -> str:
    if any(word in text for word in ("布尔", "是否")):
        return "bool"
    if any(word in text for word in ("小数", "浮点")):
        return "float"
    if any(word in text for word in ("整数", "数字", "数值")):
        return "int"
    if any(word in text for word in ("数组", "列表")):
        return "array"
    if "对象" in text:
        return "object"
    if any(word in text for word in ("日期时间", "时间")):
        return "datetime"
    if "日期" in text:
        return "date"
    return "string"


def _sample_scalar(kind: str, key: str, note: str = ""):
    kind = (kind or "string").lower()
    norm = _norm(key)
    blob = f"{norm} {note.lower()}"
    enum = _ENUM_SEARCH.search(note or "")
    if kind in _BOOL_KINDS:
        if any(word in norm for word in ("delete", "deleted", "disabled", "hidden")):
            return False
        return True
    if kind in _FLOAT_KINDS:
        if any(word in norm for word in ("amount", "price", "money", "fee", "balance")):
            return 99.9
        return 1.5
    if kind in _INT_KINDS:
        if any(word in blob for word in ("手机", "电话", "phone", "mobile")):
            return 13800138000
        if norm in {"pagesize", "pagelimit", "limit", "perpage"} or norm.endswith("pagesize"):
            return 10
        if "offset" in norm:
            return 0
        if any(word in norm for word in ("amount", "price", "money", "fee", "balance")):
            return 100
        return 1
    if kind in _DATE_KINDS:
        return "2026-01-01"
    if kind in _DATETIME_KINDS:
        return "2026-01-01 00:00:00"
    if kind == "time":
        return "12:00:00"
    if kind == "file":
        return "test.txt"
    if enum:
        return enum.group(1)
    if any(word in blob for word in ("email", "邮箱")):
        return "test@example.com"
    if any(word in blob for word in ("phone", "mobile", "tel", "手机", "电话")):
        return "13800138000"
    if any(word in blob for word in ("password", "passwd", "pwd", "密码")):
        return "Test123456"
    if "contenttype" in norm:
        return "application/json"
    if "authorization" in norm:
        return "Bearer test-token"
    if "token" in norm:
        return "test-token"
    if any(word in blob for word in ("url", "uri", "link", "网址", "链接")):
        return "https://example.com/test"
    if "地址" in note or norm.endswith("address"):
        return "北京市朝阳区测试路1号"
    if "date" in norm or "日期" in note:
        return "2026-01-01"
    if any(word in norm for word in ("time", "datetime", "timestamp")) or "时间" in note:
        return "2026-01-01 00:00:00"
    if norm in {"name", "username", "nickname", "realname", "displayname"} or any(
        word in blob for word in ("姓名", "用户名", "名称")
    ):
        return "测试用户"
    if "title" in norm or "标题" in note:
        return "测试标题"
    if any(word in blob for word in ("content", "description", "remark", "comment", "message", "desc", "内容", "备注", "描述")):
        return "测试内容"
    if _is_code_key(norm) or "编码" in note:
        return "TEST001"
    if _is_id_key(norm):
        return "1"
    if "status" in norm or "状态" in note:
        return "1"
    if norm in {"pagesize", "limit", "perpage"} or norm.endswith("pagesize"):
        return "10"
    if "page" in norm:
        return "1"
    return "test"


def _norm(key: str) -> str:
    return re.sub(r"[\s_\-]", "", key).lower()


def _is_id_key(norm: str) -> bool:
    if norm.endswith("valid"):
        return False
    return norm in {"id", "uid"} or norm.endswith("id")


def _is_code_key(norm: str) -> bool:
    if norm.endswith("encode"):
        return False
    return norm == "code" or norm.endswith("code")


def _is_layer_object(value: dict) -> bool:
    keys = set(value)
    return bool(keys) and keys <= set(_LAYER_KEYS)


def _format_layers(value: dict) -> str:
    sections = []
    for name in _LAYER_KEYS:
        if name not in value:
            continue
        item = value[name]
        if item in ({}, [], "", None):
            continue
        sections.append((name, item))
    if not sections:
        return ""
    if len(sections) == 1:
        name, item = sections[0]
        if name == "query" and _is_flat(item):
            return _query_string(item)
        return _pretty(item)
    blocks = []
    for name, item in sections:
        if name == "query" and _is_flat(item):
            blocks.append(f"query: {_query_string(item)}")
        else:
            blocks.append(f"{name}:\n{_pretty(item)}")
    return "\n\n".join(blocks)


def _is_flat(value) -> bool:
    return isinstance(value, dict) and all(not isinstance(item, (dict, list)) for item in value.values())


def _query_string(data: dict) -> str:
    parts = []
    for key, value in data.items():
        if isinstance(value, bool):
            text = "true" if value else "false"
        elif value is None:
            text = ""
        else:
            text = str(value)
        parts.append(f"{key}={text}")
    return "&".join(parts)


def _pretty(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)

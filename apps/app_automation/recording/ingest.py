# -*- coding: utf-8 -*-

_ALLOWED = {"click", "long_press", "swipe", "input"}
_DIRECTIONS = {"up", "down", "left", "right"}
_LABELS = {"click": "点击", "long_press": "长按", "swipe": "滑动", "input": "输入"}


def parse_ingested_event(payload, order, template):
    kind = (payload or {}).get("event_type")
    if kind not in _ALLOWED:
        raise ValueError("未知事件类型")
    password = bool(payload.get("password"))
    visible = "" if password else (payload.get("text") or "")
    direction = payload.get("direction") or "up"
    if direction not in _DIRECTIONS:
        direction = "up"
    try:
        distance = float(payload.get("distance") or 0)
    except (TypeError, ValueError):
        distance = 0
    distance = min(1.0, max(0.0, distance))
    label = visible or payload.get("content_desc") or payload.get("resource_id") or ""
    step = {
        "type": kind,
        "platform": "android",
        "accessibility_id": "",
        "order": order,
        "name": (_LABELS[kind] + " " + label).strip(),
        "resource_id": payload.get("resource_id") or "",
        "content_desc": payload.get("content_desc") or "",
        "text": visible,
        "class_name": payload.get("class_name") or "",
        "bounds": payload.get("bounds") or {},
        "template": template or "",
        "screen": payload.get("screen") or {},
        "password": password,
    }
    if kind in ("click", "long_press"):
        step["duration_ms"] = int(payload.get("duration_ms") or 0)
    if kind == "swipe":
        step["direction"] = direction
        step["distance"] = distance
    if kind == "input":
        step["input_text"] = "" if password else (payload.get("input_text") or payload.get("text") or "")
        if password:
            step["input_text"] = ""
            step["text"] = ""
    return step

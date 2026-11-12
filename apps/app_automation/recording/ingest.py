# -*- coding: utf-8 -*-

_ALLOWED = {"click", "long_press", "swipe", "input"}
_DIRECTIONS = {"up", "down", "left", "right"}
_LABELS = {"click": "点击", "long_press": "长按", "swipe": "滑动", "input": "输入"}
_DIRECTION_TEXT = {"up": "向上", "down": "向下", "left": "向左", "right": "向右"}
_POINT_KEYS = ("from_x", "from_y", "to_x", "to_y")


def touch_point(payload):
    if not isinstance(payload, dict):
        return None
    try:
        x = float(payload["x"])
        y = float(payload["y"])
    except (KeyError, TypeError, ValueError):
        return None
    if x < 0 or x > 1 or y < 0 or y > 1:
        return None
    return (x, y)


def finger_points(payload):
    if not isinstance(payload, dict):
        return None
    try:
        values = [float(payload[key]) for key in _POINT_KEYS]
    except (KeyError, TypeError, ValueError):
        return None
    if any(value < 0 or value > 1 for value in values):
        return None
    return values


def _direction_between(from_x, from_y, to_x, to_y):
    dx = to_x - from_x
    dy = to_y - from_y
    if abs(dx) >= abs(dy):
        return "right" if dx >= 0 else "left"
    return "down" if dy >= 0 else "up"


def _percent(value):
    return int(round(float(value) * 100))


def _contains(bounds, x, y):
    try:
        left = float(bounds["x"])
        top = float(bounds["y"])
        width = float(bounds["w"])
        height = float(bounds["h"])
        px = float(x)
        py = float(y)
    except (KeyError, TypeError, ValueError):
        return False
    return left <= px <= left + width and top <= py <= top + height


def _area(bounds):
    try:
        area = float(bounds["w"]) * float(bounds["h"])
    except (KeyError, TypeError, ValueError):
        return None
    if area <= 0:
        return None
    return area


def control_at_point(nodes, x, y):
    """Smallest control that contains the point and has visible text or a description."""
    best = None
    best_area = None
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        label = (node.get("text") or node.get("content_desc") or "").strip()
        if not label:
            continue
        bounds = node.get("bounds") or {}
        if not _contains(bounds, x, y):
            continue
        area = _area(bounds)
        if area is None:
            continue
        if best is None or area < best_area:
            best = node
            best_area = area
    return best


def label_near_point(nodes, x, y):
    """Caption sitting just under a tap, such as a launcher icon label."""
    try:
        px = float(x)
        py = float(y)
    except (TypeError, ValueError):
        return None
    best = None
    best_gap = None
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        label = (node.get("text") or node.get("content_desc") or "").strip()
        if not label or len(label) > 24:
            continue
        bounds = node.get("bounds") or {}
        area = _area(bounds)
        if area is None or area > 0.05:
            continue
        try:
            left = float(bounds["x"])
            top = float(bounds["y"])
            width = float(bounds["w"])
        except (KeyError, TypeError, ValueError):
            continue
        if px < left - 0.04 or px > left + width + 0.04:
            continue
        gap = top - py
        if gap < -0.02 or gap > 0.06:
            continue
        if best is None or gap < best_gap:
            best = node
            best_gap = gap
    return best


def apply_control_label(steps, kind, label, bounds):
    """Rename the latest matching touch step. Returns that step, or None."""
    text = (label or "").strip()
    if kind not in ("click", "long_press") or not text:
        return None
    for step in reversed(steps or []):
        if step.get("type") == "wait":
            continue
        if step.get("type") != kind or not _contains(bounds or {}, step.get("x"), step.get("y")):
            return None
        step["name"] = "%s %s" % (_LABELS[kind], text)
        step["text"] = text
        return step
    return None


def swipe_name(from_x, from_y, to_x, to_y):
    direction = _direction_between(from_x, from_y, to_x, to_y)
    return "滑动 %s 从 %s%%,%s%% 到 %s%%,%s%%" % (
        _DIRECTION_TEXT[direction],
        _percent(from_x),
        _percent(from_y),
        _percent(to_x),
        _percent(to_y),
    )


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
        point = touch_point(payload)
        if point:
            step["x"], step["y"] = (round(point[0], 4), round(point[1], 4))
            control = (payload.get("control_label") or "").strip()
            if control:
                step["name"] = "%s %s" % (_LABELS[kind], control)
                if not step["text"]:
                    step["text"] = control
            else:
                step["name"] = "%s %s%%,%s%%" % (_LABELS[kind], _percent(point[0]), _percent(point[1]))
    if kind == "swipe":
        points = finger_points(payload)
        if points:
            from_x, from_y, to_x, to_y = points
            direction = _direction_between(from_x, from_y, to_x, to_y)
            distance = min(1.0, ((to_x - from_x) ** 2 + (to_y - from_y) ** 2) ** 0.5)
            step["from_x"], step["from_y"], step["to_x"], step["to_y"] = points
            step["name"] = swipe_name(from_x, from_y, to_x, to_y)
        step["direction"] = direction
        step["distance"] = distance
    if kind == "input":
        step["input_text"] = "" if password else (payload.get("input_text") or payload.get("text") or "")
        if password:
            step["input_text"] = ""
            step["text"] = ""
    return step


def wait_step(order, duration_ms):
    return {
        "type": "wait",
        "platform": "android",
        "accessibility_id": "",
        "order": order,
        "name": "等待 %s毫秒" % int(duration_ms),
        "resource_id": "",
        "content_desc": "",
        "text": "",
        "class_name": "",
        "bounds": {},
        "template": "",
        "screen": {},
        "password": False,
        "duration_ms": int(duration_ms),
    }


def _bounds_close(left, right):
    try:
        return (
            abs(float(left.get("y")) - float(right.get("y"))) < 0.08
            and abs(float(left.get("x")) - float(right.get("x"))) < 0.08
        )
    except (AttributeError, TypeError, ValueError):
        return False


def same_input_field(previous, step):
    if previous.get("type") != "input" or step.get("type") != "input":
        return False
    if (previous.get("resource_id") or "") or (step.get("resource_id") or ""):
        return (previous.get("resource_id") or "") == (step.get("resource_id") or "")
    if (previous.get("class_name") or "") != (step.get("class_name") or ""):
        return False
    return _bounds_close(previous.get("bounds") or {}, step.get("bounds") or {})


def _keyboard_noise(step):
    if step.get("type") == "wait":
        return True
    if step.get("type") != "click":
        return False
    point = touch_point(step)
    return point is not None and point[1] >= 0.62


def _input_before_keyboard(steps):
    index = len(steps) - 1
    while index >= 0 and _keyboard_noise(steps[index]):
        index -= 1
    if index >= 0 and steps[index].get("type") == "input":
        return index
    return None


def _renumber(steps):
    for index, step in enumerate(steps, start=1):
        step["order"] = index
    return steps


def place_input(steps, step):
    """Keep one input for the field and the latest text. An empty clear does not erase it."""
    index = _input_before_keyboard(steps)
    if not (step.get("input_text") or "") and not step.get("password"):
        if index is not None and same_input_field(steps[index], step) and (steps[index].get("input_text") or ""):
            return steps, None
    if index is not None and same_input_field(steps[index], step):
        merged = dict(steps[index])
        merged["input_text"] = step.get("input_text") or ""
        if not step.get("password"):
            merged["text"] = step.get("text") or ""
            merged["name"] = step.get("name") or merged.get("name") or ""
        if step.get("bounds"):
            merged["bounds"] = step["bounds"]
        if step.get("screen"):
            merged["screen"] = step["screen"]
        if step.get("template"):
            merged["template"] = step["template"]
        head = list(steps[:index])
        while head and _keyboard_noise(head[-1]):
            head.pop()
        return _renumber(head + [merged]), merged
    return _renumber(list(steps) + [step]), step


def absorb_typing_clicks(steps):
    """A text change replaces the key taps that produced it, and keeps the field tap."""
    end = len(steps)
    while end > 0 and steps[end - 1].get("type") == "click" and touch_point(steps[end - 1]):
        end -= 1
    clicks = steps[end:]
    if not clicks:
        return steps
    if end > 0 and steps[end - 1].get("type") == "input":
        kept = steps[:end]
    elif len(clicks) >= 2:
        kept = steps[:end] + clicks[:1]
    else:
        return steps
    for index, step in enumerate(kept, start=1):
        step["order"] = index
    return kept

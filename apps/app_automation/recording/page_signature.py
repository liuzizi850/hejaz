# -*- coding: utf-8 -*-
import re

_CLOCK = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")
_VOLATILE_ID = re.compile(r"(badge|unread|clock|chrono|^count$|^time$|^timer$)")
_ANCHOR_LIMIT = 4


def _area(bounds):
    try:
        return float(bounds["w"]) * float(bounds["h"])
    except (KeyError, TypeError, ValueError):
        return None


def _plain(value):
    text = (value or "").replace("&#10;", "\n").replace("\r", "\n")
    for line in text.split("\n"):
        line = line.strip()
        if line:
            return line
    return ""


def _flat(value):
    return " ".join((value or "").replace("&#10;", " ").split()).casefold()


def _stable_text(node):
    text = _plain(node.get("text") or node.get("content_desc") or "")
    if not text or len(text) > 16 or text.isdigit() or _CLOCK.match(text):
        return ""
    return text


def _stable_id(node):
    resource_id = (node.get("resource_id") or "").strip()
    if not resource_id or resource_id.startswith("android:id/"):
        return ""
    tail = resource_id.rsplit("/", 1)[-1].lower()
    if _VOLATILE_ID.search(tail):
        return ""
    return resource_id


def stable_anchors(nodes, limit=_ANCHOR_LIMIT):
    """Up to four stable ids, then short labels. Skip clocks, badges, and full-screen nodes."""
    identifiers = []
    labels = []
    seen = set()
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        area = _area(node.get("bounds") or {})
        if area is not None and area > 0.85:
            continue
        resource_id = _stable_id(node)
        if resource_id:
            key = ("resource_id", resource_id)
            item = {"resource_id": resource_id}
            bucket = identifiers
        else:
            text = _stable_text(node)
            if not text:
                continue
            key = ("text", text)
            item = {"text": text}
            bucket = labels
        if key in seen:
            continue
        seen.add(key)
        bucket.append(item)
    return (identifiers + labels)[:limit]


def anchor_visible(nodes, anchor):
    anchor = anchor or {}
    resource_id = anchor.get("resource_id") or ""
    text = anchor.get("text") or ""
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        if resource_id and (node.get("resource_id") or "") == resource_id:
            return True
        shown = node.get("text") or node.get("content_desc") or ""
        if text and (_plain(shown) == text or _flat(shown) == _flat(text)):
            return True
    return False


def page_matches(expected, package, nodes):
    expected = expected or {}
    want = expected.get("package") or ""
    anchors = expected.get("anchors") or []
    if not want or not anchors or (package or "") != want:
        return False
    return all(anchor_visible(nodes, anchor) for anchor in anchors)


def has_start_page(page):
    page = page or {}
    return bool(page.get("package") and page.get("anchors"))


def remember_before(step, nodes):
    anchors = stable_anchors(nodes)
    if anchors and isinstance(step, dict):
        step["before"] = anchors
    return step


def remember_after(steps, nodes):
    anchors = stable_anchors(nodes)
    if not anchors:
        return None
    for step in reversed(list(steps or [])):
        if step.get("type") == "wait":
            continue
        if step.get("type") not in ("click", "long_press", "swipe", "input"):
            return None
        if step.get("after"):
            return None
        step["after"] = anchors
        return step
    return None


def component_name(package, activity):
    package = (package or "").strip()
    activity = (activity or "").strip()
    if not package or not activity:
        return ""
    if "/" in activity:
        return activity
    if activity.startswith("."):
        return "%s/%s%s" % (package, package, activity)
    return "%s/%s" % (package, activity)


def merge_screen(current, incoming):
    start_page = current.get("start_page") if isinstance(current, dict) else None
    merged = dict(incoming) if isinstance(incoming, dict) else {}
    if start_page:
        merged["start_page"] = start_page
    return merged


def event_chain_document(screen, steps):
    screen = dict(screen or {})
    start_page = screen.pop("start_page", None)
    document = {"platform": "android", "screen": screen, "steps": steps}
    if start_page:
        document["start_page"] = start_page
    return document


def _window_focus(device_id):
    import subprocess

    try:
        output = subprocess.check_output(
            ["adb", "-s", device_id, "shell", "dumpsys", "window"],
            stderr=subprocess.STDOUT,
            timeout=8,
        )
    except (subprocess.SubprocessError, OSError):
        return ""
    return output.decode("utf-8", "replace")


def capture_page(device_id):
    from apps.app_automation.recording.adb_gateway import read_ui_dump
    from apps.app_automation.recording.foreground import activity_from_focus, package_from_focus
    from apps.app_automation.recording.screen_labels import controls_from_dump

    focus = _window_focus(device_id)
    package = package_from_focus(focus)
    anchors = stable_anchors(controls_from_dump(read_ui_dump(device_id)))
    if not package or not anchors:
        return None
    return {"package": package, "activity": activity_from_focus(focus), "anchors": anchors}

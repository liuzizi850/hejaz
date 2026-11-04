# -*- coding: utf-8 -*-
from .locator import select_by_identity

CROP_TOP_RATIO = 0.08


class ScreenRecordError(Exception):
    pass


def _outcome(step, status, screenshot, reason):
    return {
        "order": step.get("order"),
        "name": step.get("name") or "",
        "type": step.get("type"),
        "status": status,
        "screenshot": screenshot or "",
        "reason": reason or "",
    }


def _locate(step, device):
    node = select_by_identity(step, device.find_nodes())
    if node is not None:
        return node
    template = step.get("template") or ""
    if template and device.match_template(template):
        return {"template": template}
    return None


def _run_action(step, device):
    kind = step.get("type")
    if kind == "wait":
        device.wait_ms(int(step.get("duration_ms") or 0))
        return _outcome(step, "passed", device.screenshot("wait"), "")
    if kind == "assert":
        missing = [text for text in (step.get("expected_texts") or []) if not device.text_exists(text)]
        for selector in step.get("expected_selectors") or []:
            if _locate(selector, device) is None:
                missing.append(selector.get("resource_id") or selector.get("text") or "控件")
        shot = device.screenshot("assert")
        if missing:
            return _outcome(step, "failed", shot, "未找到: " + ", ".join(missing))
        return _outcome(step, "passed", shot, "")
    if kind == "input" and not (step.get("input_text") or ""):
        return _outcome(step, "failed", device.screenshot("input"), "输入文字为空")
    node = _locate(step, device)
    shot = device.screenshot(kind or "step")
    if node is None:
        return _outcome(step, "failed", shot, "找不到控件")
    if kind == "click":
        device.click(node)
    elif kind == "long_press":
        device.long_press(node, int(step.get("duration_ms") or 0))
    elif kind == "swipe":
        device.swipe(node, step.get("direction") or "up", float(step.get("distance") or 0))
    elif kind == "input":
        device.input_text(node, step.get("input_text") or "")
    else:
        return _outcome(step, "failed", shot, "未知步骤类型")
    return _outcome(step, "passed", shot, "")


def replay_event_chain(steps, start_screen, device):
    current = device.screenshot("current-start")
    if not device.match_images(start_screen, current, CROP_TOP_RATIO):
        return {
            "passed": False,
            "start_screen_mismatch": True,
            "steps": [],
            "current_screen": current,
            "start_screen": start_screen,
            "videos": [],
            "screenrecord_error": "",
        }
    screenrecord_error = ""
    try:
        device.start_screenrecord()
    except ScreenRecordError as exc:
        screenrecord_error = str(exc)
    outcomes = []
    failed = False
    for step in steps:
        if failed:
            outcomes.append(_outcome(step, "skipped", "", "未执行"))
            continue
        outcome = _run_action(step, device)
        outcomes.append(outcome)
        if outcome["status"] == "failed":
            failed = True
    videos = []
    if not screenrecord_error:
        videos = device.stop_screenrecord()
    return {
        "passed": not failed,
        "start_screen_mismatch": False,
        "steps": outcomes,
        "current_screen": current,
        "start_screen": start_screen,
        "videos": videos,
        "screenrecord_error": screenrecord_error,
    }

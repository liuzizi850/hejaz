# -*- coding: utf-8 -*-
import re

from .foreground import is_launcher_package
from .ingest import finger_points, touch_point
from .locator import find_by_label, select_by_identity
from .page_signature import anchor_visible, has_start_page, page_matches

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


_COORDINATE_NAME = re.compile(r"^\d+%\s*,\s*\d+%$")


def _plain_label(value):
    text = (value or "").replace("&#10;", "\n").replace("\r", "\n")
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if not lines:
        return ""
    # "Q" plus "16h" is the post title. A one-letter first line is not a name.
    if len(lines[0]) < 2:
        return " ".join(lines)
    return lines[0]


def action_label(step):
    text = _plain_label((step or {}).get("text") or (step or {}).get("content_desc") or "")
    if text:
        return text
    name = ((step or {}).get("name") or "").strip()
    for prefix in ("点击 ", "长按 "):
        if name.startswith(prefix):
            rest = name[len(prefix):].strip()
            if rest and not _COORDINATE_NAME.match(rest):
                return rest
    return ""


def _first_coordinate_target(steps):
    for step in steps or []:
        if step.get("type") == "wait":
            continue
        if step.get("type") not in ("click", "long_press") or action_label(step):
            return None
        return touch_point(step)
    return None


def _first_named_target(steps):
    for step in steps or []:
        if step.get("type") == "wait":
            continue
        if step.get("type") not in ("click", "long_press"):
            return ""
        return action_label(step)
    return ""


def _locate(step, device):
    node = select_by_identity(step, device.find_nodes())
    if node is not None:
        return node
    template = step.get("template") or ""
    if template and device.match_template(template):
        return {"template": template}
    return None


def _locate_recorded_icon(device, start_screen, point):
    locate = getattr(device, "locate_icon", None)
    if locate is None:
        return point
    return locate(start_screen, point[0], point[1])


_OPEN_WAIT_MS = 1200


def _foreground(device):
    reader = getattr(device, "foreground_package", None)
    if reader is None:
        return ""
    try:
        return reader() or ""
    except Exception:
        return ""


def _launcher_control(step):
    resource = ((step or {}).get("resource_id") or "")
    package = resource.split("/", 1)[0] if "/" in resource else ""
    return is_launcher_package(package)


def _center(node):
    bounds = (node or {}).get("bounds") or {}
    try:
        return (
            float(bounds["x"]) + float(bounds["w"]) / 2.0,
            float(bounds["y"]) + float(bounds["h"]) / 2.0,
        )
    except (KeyError, TypeError, ValueError):
        return None


def _recorded_point_is_elsewhere(node, point):
    """The top-left back arrow often borrows the screen title. Tap where the finger was."""
    if point is None or point[1] > 0.16:
        return False
    center = _center(node)
    if center is None:
        return False
    return abs(center[0] - point[0]) > 0.18 or abs(center[1] - point[1]) > 0.08


def _named_node(device, label):
    named = find_by_label(device.find_nodes(), label)
    if named is not None:
        return named
    seek = getattr(device, "seek_label", None)
    if seek is None:
        return None
    return seek(label)


def _open_from_launcher(step, device, start_screen, label):
    """Click the control with the recorded name. Never tap a bare coordinate instead."""
    named = _named_node(device, label)
    shot = device.screenshot(_step_shot_name(step))
    if named is None:
        return _outcome(step, "failed", shot, "没有点到 " + label)
    device.click(named)
    if hasattr(device, "wait_ms"):
        device.wait_ms(_OPEN_WAIT_MS)
    if is_launcher_package(_foreground(device)):
        return _outcome(step, "failed", shot, "没有打开 " + label)
    return _outcome(step, "passed", shot, "")


def _step_shot_name(step):
    return "%s-%s" % (step.get("order"), step.get("type") or "step")


def _run_action(step, device, start_screen="", relocate_icon=False, foreground=""):
    kind = step.get("type")
    if kind == "wait":
        device.wait_ms(int(step.get("duration_ms") or 0))
        return _outcome(step, "passed", device.screenshot(_step_shot_name(step)), "")
    if kind == "assert":
        missing = [text for text in (step.get("expected_texts") or []) if not device.text_exists(text)]
        for selector in step.get("expected_selectors") or []:
            if _locate(selector, device) is None:
                missing.append(selector.get("resource_id") or selector.get("text") or "控件")
        shot = device.screenshot(_step_shot_name(step))
        if missing:
            return _outcome(step, "failed", shot, "未找到: " + ", ".join(missing))
        return _outcome(step, "passed", shot, "")
    if kind == "input" and not (step.get("input_text") or ""):
        return _outcome(step, "failed", device.screenshot(_step_shot_name(step)), "输入文字为空")
    label = action_label(step) if kind in ("click", "long_press") else ""
    if (
        kind == "click"
        and label
        and not _launcher_control(step)
        and is_launcher_package(foreground)
    ):
        return _open_from_launcher(step, device, start_screen, label)
    point = touch_point(step) if kind in ("click", "long_press") else None
    if label:
        named = find_by_label(device.find_nodes(), label)
        if named is not None and not _recorded_point_is_elsewhere(named, point):
            shot = device.screenshot(_step_shot_name(step))
            if kind == "click":
                device.click(named)
            else:
                device.long_press(named, int(step.get("duration_ms") or 0))
            return _outcome(step, "passed", shot, "")
        if point is None:
            return _outcome(step, "failed", device.screenshot(_step_shot_name(step)), "没有点到 " + label)
    if point and relocate_icon:
        found = _locate_recorded_icon(device, start_screen, point)
        if found is None:
            seek = getattr(device, "seek_icon", None)
            if seek is not None:
                found = seek(start_screen, point[0], point[1])
        shot = device.screenshot(_step_shot_name(step))
        if found is None:
            return _outcome(step, "failed", shot, "找不到这个应用")
        if kind == "click":
            device.tap_point(found[0], found[1])
        else:
            device.long_press_point(found[0], found[1], int(step.get("duration_ms") or 0))
        return _outcome(step, "passed", shot, "")
    if point and kind == "click":
        shot = device.screenshot(_step_shot_name(step))
        device.tap_point(point[0], point[1])
        return _outcome(step, "passed", shot, "")
    if point and kind == "long_press":
        shot = device.screenshot(_step_shot_name(step))
        device.long_press_point(point[0], point[1], int(step.get("duration_ms") or 0))
        return _outcome(step, "passed", shot, "")
    points = finger_points(step) if kind == "swipe" else None
    if points:
        shot = device.screenshot(_step_shot_name(step))
        device.swipe_points(*points)
        return _outcome(step, "passed", shot, "")
    node = _locate(step, device)
    shot = device.screenshot(_step_shot_name(step))
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


def _anchor_list_visible(device, anchors, require_all):
    anchors = anchors or []
    if not anchors:
        return False
    nodes = device.find_nodes()
    hits = [anchor_visible(nodes, anchor) for anchor in anchors]
    return all(hits) if require_all else any(hits)


def _launcher_page(anchors):
    packages = []
    for anchor in anchors or []:
        resource = anchor.get("resource_id") or ""
        if ":id/" in resource:
            packages.append(resource.split(":id/", 1)[0])
        elif "/" in resource:
            packages.append(resource.split("/", 1)[0])
    return bool(packages) and all(is_launcher_package(package) for package in packages)


def _coordinate_on_wrong_page(step, device):
    """A bare point belongs to the page it was recorded on. Do not tap it anywhere else."""
    if action_label(step) or step.get("type") not in ("click", "long_press"):
        return None
    if touch_point(step) is None or not step.get("before"):
        return None
    on_recorded_page = _anchor_list_visible(device, step.get("before"), require_all=False)
    if _launcher_page(step.get("before")) and not is_launcher_package(_foreground(device)):
        on_recorded_page = False
    if on_recorded_page:
        return None
    shot = device.screenshot(_step_shot_name(step))
    if _anchor_list_visible(device, step.get("after"), require_all=True):
        return _outcome(step, "passed", shot, "")
    return _outcome(step, "failed", shot, "不在录制的那一页")


_BACK_LIMIT = 4
_BACK_WAIT_MS = 700


def _first_launcher_point(steps):
    for step in steps or []:
        if step.get("type") not in ("click", "long_press") or action_label(step):
            continue
        point = touch_point(step)
        if point is None:
            continue
        if _launcher_page(step.get("before")) or _launcher_page(step.get("after")) or not step.get("before"):
            return point
    return None


def _try_open_recorded_app(step, steps, device, start_screen):
    """The recorded point missed the icon. Find that icon and open the app."""
    if action_label(step) or step.get("type") not in ("click", "long_press"):
        return False
    if not is_launcher_package(_foreground(device)):
        return False
    if not step.get("after") or _launcher_page(step.get("after")):
        return False
    if _anchor_list_visible(device, step.get("after"), require_all=True):
        return False
    point = _first_launcher_point(steps) or touch_point(step)
    if point is None or not start_screen:
        return False
    found = _locate_recorded_icon(device, start_screen, point)
    if found is None:
        seek = getattr(device, "seek_icon", None)
        if seek is not None:
            found = seek(start_screen, point[0], point[1])
    if found is None:
        return False
    device.tap_point(found[0], found[1])
    if hasattr(device, "wait_ms"):
        device.wait_ms(_OPEN_WAIT_MS)
    return not is_launcher_package(_foreground(device))


def _visible_labels(nodes):
    labels = []
    for node in nodes or []:
        label = _plain_label((node or {}).get("text") or (node or {}).get("content_desc") or "")
        if label and label not in labels:
            labels.append(label)
        if len(labels) >= 4:
            break
    return labels


def _show_recorded_home(step, device):
    """A short bottom swipe opens recents. The recorded result is the launcher itself."""
    anchors = (step or {}).get("after") or []
    if action_label(step) or not _launcher_page(anchors):
        return
    if _anchor_list_visible(device, anchors, require_all=True):
        return
    if not is_launcher_package(_foreground(device)):
        return
    home = getattr(device, "press_home", None)
    if home is None:
        return
    home()
    if hasattr(device, "wait_ms"):
        device.wait_ms(_BACK_WAIT_MS)


def _after_reason(step, device):
    """A step passes when the recorded next page shows up. A typed value must read back."""
    anchors = (step or {}).get("after") or []
    if not anchors:
        return ""
    nodes = device.find_nodes()
    if step.get("type") == "input" and (step.get("input_text") or ""):
        shown = _plain_label((select_by_identity(step, nodes) or {}).get("text") or "")
        if shown and shown != step.get("input_text"):
            return "输入内容不一致"
    if all(anchor_visible(nodes, anchor) for anchor in anchors):
        return ""
    # A desktop tap often opens the app before the dump catches up, so the
    # recorded "after" is still the launcher. Leaving the launcher is the result.
    if (
        not action_label(step)
        and _launcher_page(anchors)
        and not is_launcher_package(_foreground(device))
    ):
        return ""
    before = step.get("before") or []
    if before and all(anchor_visible(nodes, anchor) for anchor in before):
        return "点了但页面没变"
    labels = _visible_labels(nodes)
    if labels:
        return "进了别的页面: " + ", ".join(labels)
    return "进了别的页面"


def _align_start_page(device, start_page):
    """Back up inside the app, then cold-start it, until the recorded page is on screen."""
    package = (start_page or {}).get("package") or ""

    def matches():
        return page_matches(start_page, _foreground(device), device.find_nodes())

    if matches():
        return True
    if package and _foreground(device) == package:
        back = getattr(device, "press_back", None)
        if back is not None:
            for _ in range(_BACK_LIMIT):
                if is_launcher_package(_foreground(device)):
                    break
                back()
                if hasattr(device, "wait_ms"):
                    device.wait_ms(_BACK_WAIT_MS)
                if is_launcher_package(_foreground(device)):
                    break
                if matches():
                    return True
    restart = getattr(device, "restart_app", None)
    if restart is None or not package:
        return False
    restart(package, (start_page or {}).get("activity") or "")
    if hasattr(device, "wait_ms"):
        device.wait_ms(_OPEN_WAIT_MS)
    return matches()


def _mismatch(current, start_screen):
    return {
        "passed": False,
        "start_screen_mismatch": True,
        "steps": [],
        "current_screen": current,
        "start_screen": start_screen,
        "videos": [],
        "screenrecord_error": "",
    }


def execution_progress(done, total):
    """Map finished steps onto the 10–90 range used while a run is in progress."""
    if not total:
        return 10
    return min(90, 10 + int(80 * done / total))


def replay_event_chain(steps, start_screen, device, on_step=None, start_page=None):
    current = device.screenshot("current-start")
    if has_start_page(start_page):
        if not _align_start_page(device, start_page):
            return _mismatch(current, start_screen)
    else:
        image_matches = device.match_images(start_screen, current, CROP_TOP_RATIO)
        if not image_matches:
            label = _first_named_target(steps)
            found = find_by_label(device.find_nodes(), label) if label else None
            can_seek_icon = (
                not label
                and getattr(device, "locate_icon", None) is not None
                and _first_coordinate_target(steps) is not None
            )
            if found is None and not can_seek_icon:
                return _mismatch(current, start_screen)
    screenrecord_error = ""
    try:
        device.start_screenrecord()
    except ScreenRecordError as exc:
        screenrecord_error = str(exc)
    outcomes = []
    failed = False
    relocate_pending = True
    steps = list(steps or [])
    total = len(steps)
    done = 0
    index = 0
    while index < total:
        step = steps[index]
        kind = step.get("type")
        foreground = _foreground(device)
        relocate = (
            relocate_pending
            and kind in ("click", "long_press")
            and not action_label(step)
            and touch_point(step) is not None
        )
        outcome = _coordinate_on_wrong_page(step, device)
        if outcome is None:
            outcome = _run_action(
                step, device, start_screen=start_screen, relocate_icon=relocate, foreground=foreground,
            )
        outcomes.append(outcome)
        if kind != "wait":
            relocate_pending = False
        if outcome["status"] == "failed":
            failed = True
        done += 1
        if on_step is not None:
            on_step(done, total)
        reason = str(outcome.get("reason") or "")
        if reason.startswith("没有打开") or reason.startswith("没有点到"):
            break
        if outcome["status"] == "passed" and kind in ("click", "long_press", "swipe", "input"):
            cursor = index + 1
            while cursor < total and steps[cursor].get("type") == "wait":
                wait = steps[cursor]
                outcomes.append(_run_action(wait, device))
                done += 1
                if on_step is not None:
                    on_step(done, total)
                cursor += 1
            if is_launcher_package(_foreground(device)):
                _try_open_recorded_app(step, steps, device, start_screen)
            _show_recorded_home(step, device)
            reason = _after_reason(step, device)
            # The next step looks for its own control. Do not press back hunting
            # for that name, and do not fail this step when the name is "Q".
            if outcome["status"] == "passed" and reason and cursor >= total:
                outcome["status"] = "failed"
                outcome["reason"] = reason
                outcome["screenshot"] = device.screenshot(_step_shot_name(step))
                failed = True
                break
            index = cursor
            continue
        index += 1
    videos = []
    if not screenrecord_error:
        try:
            videos = device.stop_screenrecord()
        except ScreenRecordError as exc:
            screenrecord_error = str(exc)
            videos = []
    return {
        "passed": not failed,
        "start_screen_mismatch": False,
        "steps": outcomes,
        "current_screen": current,
        "start_screen": start_screen,
        "videos": videos,
        "screenrecord_error": screenrecord_error,
    }

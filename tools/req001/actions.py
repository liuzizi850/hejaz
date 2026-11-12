# -*- coding: utf-8 -*-
"""Whitelist UI actions executed through ADB (and Airtest wrappers when present)."""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from tools.req001.errors import ActionError
from tools.req001.adb_utils import run_adb
from tools.req001.ui_observe import UiNode

WHITELIST = {
    "launch_app",
    "click",
    "input",
    "wait",
    "assert_text",
    "assert_app_foreground",
    "step_done",
    "fail",
}


@dataclass
class ActionResult:
    ok: bool
    message: str = ""
    assertion_failed: bool = False
    step_done: bool = False
    abort: bool = False


def validate_action(data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(data, dict):
        raise ActionError("动作不是 JSON 对象")
    name = str(data.get("action") or "").strip()
    if name not in WHITELIST:
        raise ActionError(f"非法动作「{name or '?'}」不在白名单中: {sorted(WHITELIST)}")
    return data


def _find_node(nodes: Sequence[UiNode], text: Optional[str] = None, resource_id: Optional[str] = None) -> Optional[UiNode]:
    text_l = (text or "").strip()
    rid = (resource_id or "").strip()
    for node in nodes:
        if rid:
            if node.resource_id == rid or node.resource_id.endswith(f"/{rid}") or node.resource_id.endswith(rid):
                return node
        if text_l:
            if node.text == text_l or node.content_desc == text_l:
                return node
    if text_l:
        text_low = text_l.lower()
        for node in nodes:
            if text_low in (node.text or "").lower() or text_low in (node.content_desc or "").lower():
                return node
    return None


def _tap(adb: Path, serial: str, x: int, y: int) -> None:
    result = run_adb(adb, ["shell", "input", "tap", str(x), str(y)], serial=serial, timeout=15)
    if result.returncode != 0:
        raise ActionError(f"点击失败: {(result.stderr or result.stdout or '').strip()}")


def _input_text(adb: Path, serial: str, text: str) -> None:
    # adb input text treats space as %s; keep this conservative.
    escaped = text.replace(" ", "%s").replace("'", "")
    result = run_adb(adb, ["shell", "input", "text", escaped], serial=serial, timeout=20)
    if result.returncode != 0:
        raise ActionError(f"输入失败: {(result.stderr or result.stdout or '').strip()}")


def _foreground_package(adb: Path, serial: str) -> str:
    for args in (
        ["shell", "dumpsys", "window", "windows"],
        ["shell", "dumpsys", "activity", "activities"],
        ["shell", "dumpsys", "activity", "recents"],
    ):
        result = run_adb(adb, args, serial=serial, timeout=20)
        text = result.stdout or ""
        for key in ("mCurrentFocus", "mFocusedApp", "mResumedActivity", "topResumedActivity"):
            for line in text.splitlines():
                if key in line:
                    # e.g. mCurrentFocus=Window{.. com.pkg/com.pkg.Activity}
                    if "/" in line:
                        left = line.split("/")[0]
                        pkg = left.split()[-1].split("{")[-1]
                        if "." in pkg:
                            return pkg.strip()
    # dumpsys activity record
    result = run_adb(
        adb,
        ["shell", "dumpsys", "activity", "activities"],
        serial=serial,
        timeout=20,
    )
    for line in (result.stdout or "").splitlines():
        if "u0 " in line and "/" in line:
            try:
                mid = line.split("u0 ", 1)[1]
                pkg = mid.split("/", 1)[0].strip()
                if "." in pkg:
                    return pkg
            except IndexError:
                continue
    return ""


def _launch_with_adb(adb: Path, serial: str, package: str) -> None:
    # Resolve a launcher activity without hard-coding it.
    result = run_adb(
        adb,
        [
            "shell",
            "cmd",
            "package",
            "resolve-activity",
            "--brief",
            "-a",
            "android.intent.action.MAIN",
            "-c",
            "android.intent.category.LAUNCHER",
            package,
        ],
        serial=serial,
        timeout=20,
    )
    activity = ""
    for line in (result.stdout or "").splitlines():
        if "/" in line and package in line:
            activity = line.strip().split()[-1]
            break
    if activity:
        started = run_adb(
            adb,
            ["shell", "am", "start", "-n", activity],
            serial=serial,
            timeout=20,
        )
        if started.returncode == 0 and "Error" not in (started.stdout or "") and "Error" not in (started.stderr or ""):
            return
    # Fallback: monkey launcher (widely available)
    monkey = run_adb(
        adb,
        ["shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"],
        serial=serial,
        timeout=20,
    )
    if monkey.returncode != 0:
        raise ActionError(f"启动应用失败: {(monkey.stderr or monkey.stdout or '').strip()}")


def _try_airtest_start(device_id: str, package: str) -> bool:
    try:
        from apps.app_automation.utils.airtest_base import AirtestBase
    except Exception:
        return False
    try:
        base = AirtestBase(device_id=device_id)
        if not base.is_connected and not base.setup_airtest():
            return False
        return bool(base.open_app(package))
    except Exception:
        return False


def execute_action(
    action: Dict[str, Any],
    *,
    adb: Path,
    serial: str,
    app_package: str,
    nodes: Sequence[UiNode],
) -> ActionResult:
    data = validate_action(action)
    name = data["action"]

    if name == "step_done":
        return ActionResult(ok=True, step_done=True, message="步骤完成")

    if name == "fail":
        reason = str(data.get("reason") or data.get("message") or "执行器主动失败")
        return ActionResult(ok=False, abort=True, message=reason)

    if name == "wait":
        seconds = float(data.get("seconds") or data.get("timeout") or 1)
        time.sleep(max(0.0, min(seconds, 30)))
        return ActionResult(ok=True, message=f"等待 {seconds}s")

    if name == "launch_app":
        if not _try_airtest_start(serial, app_package):
            _launch_with_adb(adb, serial, app_package)
        time.sleep(1.5)
        return ActionResult(ok=True, message=f"已启动 {app_package}")

    if name == "click":
        bounds = data.get("bounds")
        if isinstance(bounds, (list, tuple)) and len(bounds) >= 2:
            if len(bounds) == 2:
                x, y = int(bounds[0]), int(bounds[1])
            else:
                x = (int(bounds[0]) + int(bounds[2])) // 2
                y = (int(bounds[1]) + int(bounds[3])) // 2
            _tap(adb, serial, x, y)
            return ActionResult(ok=True, message=f"点击 ({x},{y})")
        node = _find_node(nodes, text=data.get("text"), resource_id=data.get("resource_id") or data.get("resource-id"))
        if node and node.center:
            x, y = node.center
            _tap(adb, serial, x, y)
            return ActionResult(ok=True, message=f"点击「{node.visible_text or node.resource_id}」({x},{y})")
        raise ActionError(f"找不到可点击目标: text={data.get('text')!s} resource_id={data.get('resource_id')!s}")

    if name == "input":
        text = str(data.get("text") or data.get("value") or "")
        if not text:
            raise ActionError("input 动作缺少 text")
        node = _find_node(nodes, text=data.get("target_text"), resource_id=data.get("resource_id"))
        if node and node.center:
            _tap(adb, serial, *node.center)
            time.sleep(0.3)
        _input_text(adb, serial, text)
        return ActionResult(ok=True, message="已输入文本")

    if name == "assert_text":
        expected = str(data.get("text") or data.get("expected") or "")
        if not expected:
            raise ActionError("assert_text 缺少 text")
        blob = " ".join((n.text + " " + n.content_desc) for n in nodes)
        if expected in blob:
            return ActionResult(ok=True, message=f"断言成功：看到「{expected}」")
        return ActionResult(
            ok=False,
            assertion_failed=True,
            abort=True,
            message=f"断言失败：期望看到「{expected}」，实际界面未出现该文本",
        )

    if name == "assert_app_foreground":
        current = _foreground_package(adb, serial)
        if current == app_package or (current and app_package and current.startswith(app_package)):
            return ActionResult(ok=True, message=f"被测应用在前台: {current}")
        # Also accept if hierarchy nodes belong to the package
        if any(n.package == app_package for n in nodes if n.package):
            return ActionResult(ok=True, message=f"界面层级属于 {app_package}")
        return ActionResult(
            ok=False,
            assertion_failed=True,
            abort=True,
            message=f"断言失败：期望被测应用 {app_package} 在前台，实际焦点为 {current or '未知'}",
        )

    raise ActionError(f"未实现的动作: {name}")

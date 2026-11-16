# -*- coding: utf-8 -*-
"""Detect a visible calculator keypad and try to recover a blank Flutter UI."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Iterable, Optional, Sequence, Union

from tools.req001.bdd_parser import Scenario
from tools.req001.ui_observe import UiNode

DumpResult = Union[Sequence[UiNode], tuple]

DumpFn = Callable[[], DumpResult]
VoidFn = Callable[[], None]

REQUIRED_KEYS = ("1", "+", "=")
KEY_ALIASES = {
    "1": frozenset({"1"}),
    "+": frozenset({"+", "＋"}),
    "=": frozenset({"=", "＝"}),
}

KEYPAD_MISSING_HINT = (
    "计算器数字键区不可见（可能出现空白键区）。"
    "请重启模拟器后重新运行同一条命令。"
)
KEYPAD_MISSING_HINT_NO_REBOOT = (
    "计算器数字键区不可见（可能出现空白键区）。"
    "请确认设备已亮屏且键区完整显示后重试，当前不会自动重启设备。"
)
DEFAULT_RENDER_RETRIES = 3
DEFAULT_RENDER_DELAY_S = 1.0


def _labels_from_nodes(nodes: Iterable[UiNode]) -> set:
    labels = set()
    for node in nodes:
        for raw in (node.text, node.content_desc, getattr(node, "visible_text", "")):
            if raw and str(raw).strip():
                labels.add(str(raw).strip())
    return labels


def keypad_is_visible(nodes: Sequence[UiNode], required: Sequence[str] = REQUIRED_KEYS) -> bool:
    """True when the required calculator keys are present as text or content-desc."""
    labels = _labels_from_nodes(nodes)
    for key in required:
        aliases = KEY_ALIASES.get(key, frozenset({key}))
        if not any(label in aliases for label in labels):
            return False
    return True


def scenario_needs_keypad(scenario: Scenario) -> bool:
    cid = (scenario.case_id or "").upper()
    if cid in {"REQ-001-S2", "REQ-001-S3"} or cid.endswith("-S2") or cid.endswith("-S3"):
        return True
    blob = (scenario.name or "") + " " + " ".join(step.text for step in scenario.steps)
    return any(token in blob for token in ("1+1", "计算", "等于", "结果"))


def _nodes_from_dump(result: DumpResult) -> Sequence[UiNode]:
    if isinstance(result, tuple):
        return result[0] or []
    return result or []


@dataclass
class KeypadReady:
    visible: bool
    recovered_by: str  # "", "app_relaunch", "emulator_reboot"
    message: str


def keypad_missing_message(*, reboot_allowed: bool, is_emulator: Optional[bool] = None) -> str:
    """Avoid telling testers to reboot an emulator when this is a phone or reboot is forbidden."""
    if is_emulator is False or not reboot_allowed:
        return KEYPAD_MISSING_HINT_NO_REBOOT
    return KEYPAD_MISSING_HINT


def ensure_keypad_ready(
    dump_fn: DumpFn,
    relaunch_fn: Optional[VoidFn] = None,
    reboot_fn: Optional[VoidFn] = None,
    *,
    is_emulator: Optional[bool] = None,
    render_retries: int = DEFAULT_RENDER_RETRIES,
    render_delay_s: float = DEFAULT_RENDER_DELAY_S,
    sleep_fn: Optional[Callable[[float], None]] = None,
) -> KeypadReady:
    """If number keys are missing, retry briefly for render/rotation, then relaunch, then the emulator."""
    sleeper = sleep_fn or time.sleep
    attempts = max(1, int(render_retries))

    def _wait_for_visible(recovered_by: str, ok_message: str) -> Optional[KeypadReady]:
        for index in range(attempts):
            nodes = _nodes_from_dump(dump_fn())
            if keypad_is_visible(nodes):
                if recovered_by:
                    return KeypadReady(True, recovered_by, ok_message)
                if index > 0:
                    return KeypadReady(True, "retry", "等待渲染后计算器键区可见")
                return KeypadReady(True, "", ok_message)
            if index < attempts - 1:
                sleeper(render_delay_s)
        return None

    found = _wait_for_visible("", "计算器键区可见")
    if found is not None:
        return found

    if relaunch_fn is not None:
        relaunch_fn()
        found = _wait_for_visible("app_relaunch", "已重启被测应用并恢复计算器键区")
        if found is not None:
            return found

    if reboot_fn is not None:
        reboot_fn()
        found = _wait_for_visible("emulator_reboot", "已重启模拟器并恢复计算器键区")
        if found is not None:
            return found

    return KeypadReady(
        False,
        "",
        keypad_missing_message(reboot_allowed=reboot_fn is not None, is_emulator=is_emulator),
    )

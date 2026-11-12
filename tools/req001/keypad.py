# -*- coding: utf-8 -*-
"""Detect a visible calculator keypad and try to recover a blank Flutter UI."""
from __future__ import annotations

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


def ensure_keypad_ready(
    dump_fn: DumpFn,
    relaunch_fn: Optional[VoidFn] = None,
    reboot_fn: Optional[VoidFn] = None,
) -> KeypadReady:
    """If number keys are missing, try relaunching the app, then the emulator."""
    nodes = _nodes_from_dump(dump_fn())
    if keypad_is_visible(nodes):
        return KeypadReady(True, "", "计算器键区可见")

    if relaunch_fn is not None:
        relaunch_fn()
        nodes = _nodes_from_dump(dump_fn())
        if keypad_is_visible(nodes):
            return KeypadReady(True, "app_relaunch", "已重启被测应用并恢复计算器键区")

    if reboot_fn is not None:
        reboot_fn()
        nodes = _nodes_from_dump(dump_fn())
        if keypad_is_visible(nodes):
            return KeypadReady(True, "emulator_reboot", "已重启模拟器并恢复计算器键区")

    return KeypadReady(False, "", KEYPAD_MISSING_HINT)

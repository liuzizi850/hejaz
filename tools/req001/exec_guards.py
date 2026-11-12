# -*- coding: utf-8 -*-
"""Small, testable execution guards for click targeting, repeat clicks, and early stop."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence, Tuple

from tools.req001.bdd_parser import Scenario, Step
from tools.req001.ui_observe import UiNode

# ---------------------------------------------------------------------------
# 3) Keypad / click targeting: prefer control text, content-desc, and bounds
# ---------------------------------------------------------------------------

_DISPLAY_CLASS_HINTS = ("EditText", "TextField", "AutoCompleteTextView")
_EXPR_RE = re.compile(r"(\d+)\s*[+＋]\s*(\d+)")
_RESULT_RE = re.compile(r"(?:结果|等于|断言等于)\s*([+-]?\d+(?:\.\d+)?)")
_NUMBER_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?$")


def screen_width(nodes: Sequence[UiNode]) -> int:
    width = 0
    for node in nodes:
        if node.bounds and len(node.bounds) == 4:
            width = max(width, node.bounds[2])
    return width


def is_display_like(node: UiNode, screen_w: int = 0) -> bool:
    """True for calculator display / text fields, not compact keypad keys."""
    cls = node.class_name or ""
    if any(hint.lower() in cls.lower() for hint in _DISPLAY_CLASS_HINTS):
        return True
    if not node.bounds or len(node.bounds) != 4:
        return False
    x1, y1, x2, y2 = node.bounds
    width, height = max(0, x2 - x1), max(0, y2 - y1)
    if width <= 0 or height <= 0:
        return False
    if screen_w and width >= int(screen_w * 0.7) and width > height * 1.5:
        return True
    if width >= 600 and width > height * 2:
        return True
    return False


def is_key_like(node: UiNode, screen_w: int = 0) -> bool:
    if is_display_like(node, screen_w):
        return False
    if not node.bounds or len(node.bounds) != 4:
        return False
    x1, y1, x2, y2 = node.bounds
    width, height = max(0, x2 - x1), max(0, y2 - y1)
    if width <= 0 or height <= 0:
        return False
    if screen_w and width >= int(screen_w * 0.5) and width > height * 1.5:
        return False
    if width >= 500 and width > height * 1.5:
        return False
    return True


def _exact_label_match(node: UiNode, label: str) -> bool:
    if not label:
        return False
    return node.text == label or node.content_desc == label


def _contains_label(node: UiNode, label: str) -> bool:
    if not label:
        return False
    low = label.lower()
    return low in (node.text or "").lower() or low in (node.content_desc or "").lower()


def score_click_candidate(node: UiNode, label: str, screen_w: int = 0) -> int:
    """Higher is better. Display widgets that reuse a key's text score much lower than the key."""
    score = 0
    if _exact_label_match(node, label):
        score += 100
        # Prefer the compact key whose content-desc (or text) is exactly the key.
        if node.content_desc == label and is_key_like(node, screen_w):
            score += 30
    elif _contains_label(node, label):
        score += 15
    else:
        return -1000
    if is_display_like(node, screen_w):
        score -= 90
    elif is_key_like(node, screen_w):
        score += 50
    if node.clickable and not is_display_like(node, screen_w):
        score += 20
    if node.bounds and len(node.bounds) == 4:
        area = max(0, node.bounds[2] - node.bounds[0]) * max(0, node.bounds[3] - node.bounds[1])
        score -= min(area // 40000, 40)
    return score


@dataclass
class ClickTarget:
    x: int
    y: int
    label: str = ""
    source: str = ""  # resource_id | text | content_desc | bounds | xy


def resolve_click_target(data: dict, nodes: Sequence[UiNode]) -> Optional[ClickTarget]:
    """Resolve a click from widget text / content-desc / bounds; raw x,y is last resort.

    When a label is present, a matching keypad control wins over guessed coordinates
    (including the calculator display, whose text often equals the last key).
    """
    from tools.req001.actions import _click_label, _parse_bounds_value

    label = _click_label(data)
    resource_id = str(data.get("resource_id") or data.get("resource-id") or "").strip()
    screen_w = screen_width(nodes)

    def _from_node(node: UiNode, source: str, used_label: str) -> Optional[ClickTarget]:
        if not node or not node.center:
            return None
        x, y = node.center
        return ClickTarget(x=x, y=y, label=used_label or node.visible_text or node.resource_id, source=source)

    if resource_id:
        for node in nodes:
            rid = node.resource_id or ""
            if rid == resource_id or rid.endswith(f"/{resource_id}") or rid.endswith(resource_id):
                target = _from_node(node, "resource_id", label or resource_id)
                if target:
                    return target

    if label:
        ranked: List[Tuple[int, UiNode]] = []
        for node in nodes:
            sc = score_click_candidate(node, label, screen_w)
            if sc > 0:
                ranked.append((sc, node))
        ranked.sort(key=lambda item: item[0], reverse=True)
        if ranked:
            node = ranked[0][1]
            source = "content_desc" if node.content_desc == label else "text"
            target = _from_node(node, source, label)
            if target:
                return target

    bounds = _parse_bounds_value(data.get("bounds") or data.get("xy"))
    if bounds and len(bounds) >= 2:
        if len(bounds) == 2:
            x, y = int(bounds[0]), int(bounds[1])
        else:
            x = (int(bounds[0]) + int(bounds[2])) // 2
            y = (int(bounds[1]) + int(bounds[3])) // 2
        # If the bounds belong to a known control, keep the label for traces.
        return ClickTarget(x=x, y=y, label=label, source="bounds")

    if data.get("x") is not None and data.get("y") is not None:
        try:
            x, y = int(data["x"]), int(data["y"])
        except (TypeError, ValueError):
            return None
        # Snap to a compact key that contains this point when possible.
        for node in nodes:
            if not node.bounds or len(node.bounds) != 4 or is_display_like(node, screen_w):
                continue
            x1, y1, x2, y2 = node.bounds
            if x1 <= x <= x2 and y1 <= y <= y2 and is_key_like(node, screen_w) and node.center:
                return ClickTarget(x=node.center[0], y=node.center[1], label=node.visible_text or label, source="text")
        return ClickTarget(x=x, y=y, label=label, source="xy")
    return None


# ---------------------------------------------------------------------------
# 1) After a click, do not repeat the same coordinates if the screen is unchanged
# ---------------------------------------------------------------------------

def hierarchy_fingerprint(nodes: Sequence[UiNode]) -> str:
    """Stable description of visible widget text/desc/bounds. Status bars are ignored."""
    parts: List[str] = []
    for node in nodes:
        rid = node.resource_id or ""
        if rid.endswith("statusBarBackground") or rid.endswith("navigationBarBackground"):
            continue
        bounds = ",".join(str(v) for v in (node.bounds or []))
        parts.append(f"{node.text}|{node.content_desc}|{rid}|{bounds}")
    return "\n".join(parts)


class RepeatClickGuard:
    """Block re-clicking the same coordinates when the previous click did not change the UI."""

    def __init__(self, same_px: int = 8):
        self.same_px = same_px
        self._blocked: List[Tuple[int, int]] = []
        self._pending_xy: Optional[Tuple[int, int]] = None
        self._pending_pre_fp: Optional[str] = None
        self._last_fp: Optional[str] = None

    @property
    def blocked(self) -> Tuple[Tuple[int, int], ...]:
        return tuple(self._blocked)

    def observe(self, fingerprint: str) -> None:
        """Call at the start of each loop with the current screen fingerprint."""
        if self._pending_xy is not None and self._pending_pre_fp is not None:
            if fingerprint == self._pending_pre_fp:
                self._block(self._pending_xy)
        self._last_fp = fingerprint
        self._pending_xy = None
        self._pending_pre_fp = None

    def blocks(self, xy: Optional[Tuple[int, int]]) -> bool:
        if not xy:
            return False
        x, y = xy
        for bx, by in self._blocked:
            if abs(bx - x) <= self.same_px and abs(by - y) <= self.same_px:
                return True
        return False

    def record_click(self, xy: Tuple[int, int]) -> None:
        """Record a click that was actually sent, compared against the last observe()."""
        self._pending_xy = xy
        self._pending_pre_fp = self._last_fp

    def reject_message(self, xy: Tuple[int, int]) -> str:
        return (
            f"屏幕未变化，拒绝重复点击同一坐标 ({xy[0]},{xy[1]})，"
            "请改用控件 text / content_desc / bounds 定位其他按键"
        )

    def _block(self, xy: Tuple[int, int]) -> None:
        if not self.blocks(xy):
            self._blocked.append(xy)


# ---------------------------------------------------------------------------
# 2) End a calculation case once the expression and result are already visible
# ---------------------------------------------------------------------------

@dataclass
class CalcExpectation:
    expression: str  # normalized, e.g. "1+1"
    expected_result: str


@dataclass
class CalcCompletion:
    kind: str  # "none" | "when_done" | "pass_case" | "fail_case"
    message: str = ""
    actual: str = ""
    expected: str = ""


def normalize_expr(value: str) -> str:
    return (
        (value or "")
        .replace(" ", "")
        .replace("＋", "+")
        .replace("＝", "=")
        .replace("×", "*")
        .replace("÷", "/")
    )


def extract_calc_expectation(scenario: Scenario) -> Optional[CalcExpectation]:
    steps = list(getattr(scenario, "steps", []) or [])
    blob = " ".join(step.text for step in steps)
    name = getattr(scenario, "name", "") or ""
    expr_match = _EXPR_RE.search(blob) or _EXPR_RE.search(name)
    if not expr_match:
        return None
    expression = f"{expr_match.group(1)}+{expr_match.group(2)}"
    expected = None
    then_blobs = [step.text for step in steps if (step.keyword or "").lower() in {"then", "那么", "则"}]
    for text in reversed(then_blobs or [blob, name]):
        match = _RESULT_RE.search(text or "")
        if match:
            expected = match.group(1)
            break
    if expected is None:
        # Fall back to "等于 N" in the case name only when no Then number exists.
        match = _RESULT_RE.search(name)
        if match:
            expected = match.group(1)
    if expected is None:
        return None
    return CalcExpectation(expression=expression, expected_result=expected)


def display_texts(nodes: Sequence[UiNode]) -> List[str]:
    screen_w = screen_width(nodes)
    texts: List[str] = []
    for node in nodes:
        raw = (node.text or "").strip()
        if not raw:
            continue
        if is_display_like(node, screen_w) or "EditText" in (node.class_name or ""):
            texts.append(raw)
    if texts:
        return texts
    # Fallback: any node text that looks like an expression or bare result.
    for node in nodes:
        raw = (node.text or "").strip()
        if raw and (any(ch in raw for ch in "+＋=＝") or _NUMBER_RE.match(normalize_expr(raw))):
            texts.append(raw)
    return texts


def equals_pressed(history: Iterable[str]) -> bool:
    for item in history:
        text = str(item)
        if "click" not in text.lower():
            continue
        if "「=」" in text or "「＝」" in text:
            return True
    return False


def history_supports_expression(history: Iterable[str], expression: str) -> bool:
    """True when traces show the expression keys were used (e.g. 1, +, 1)."""
    expr = normalize_expr(expression)
    parts = re.findall(r"\d+|[+]", expr)
    labels_clicked: List[str] = []
    for item in history:
        found = re.findall(r"点击「([^」]+)」", str(item))
        labels_clicked.extend(found)
    remaining = list(parts)
    for label in labels_clicked:
        token = normalize_expr(label)
        if remaining and token == remaining[0]:
            remaining.pop(0)
    return not remaining


def recognized_result(
    nodes: Sequence[UiNode],
    expression: str,
    history: Sequence[str] = (),
) -> Optional[str]:
    """Return the visible calculation result when the expression has been evaluated."""
    expr = normalize_expr(expression)
    texts = display_texts(nodes)
    for raw in texts:
        normalized = normalize_expr(raw)
        if "=" in normalized:
            left, right = normalized.rsplit("=", 1)
            if left == expr and _NUMBER_RE.match(right or ""):
                return right
        if normalized == expr:
            # Expression entered but equals not yet applied.
            continue
    if equals_pressed(history) and history_supports_expression(history, expression):
        for raw in texts:
            normalized = normalize_expr(raw)
            if _NUMBER_RE.match(normalized):
                return normalized
    return None


def is_then_step(step: Optional[Step]) -> bool:
    if step is None:
        return False
    return (step.keyword or "").lower() in {"then", "那么", "则"}


def evaluate_calc_completion(
    scenario: Scenario,
    step: Optional[Step],
    nodes: Sequence[UiNode],
    history: Sequence[str],
) -> CalcCompletion:
    """If expression and result are already on screen, finish the step or the case."""
    expectation = extract_calc_expectation(scenario)
    if expectation is None:
        return CalcCompletion(kind="none")
    actual = recognized_result(nodes, expectation.expression, history)
    if actual is None:
        return CalcCompletion(kind="none")
    expected = expectation.expected_result
    if is_then_step(step):
        if actual == expected:
            return CalcCompletion(
                kind="pass_case",
                actual=actual,
                expected=expected,
                message=f"已识别表达式 {expectation.expression} 与结果 {actual}，提前结束用例",
            )
        return CalcCompletion(
            kind="fail_case",
            actual=actual,
            expected=expected,
            message=f"断言失败：期望看到「{expected}」，实际结果为「{actual}」",
        )
    # Given/When: the calculation is done; close this step so the Then can assert immediately.
    return CalcCompletion(
        kind="when_done",
        actual=actual,
        expected=expected,
        message=f"已识别表达式 {expectation.expression} 与结果 {actual}，提前结束当前步骤",
    )

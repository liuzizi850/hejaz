# -*- coding: utf-8 -*-
"""Unit tests for REQ-001/REQ-002 execution speed and click guards."""
from __future__ import annotations

import json
from pathlib import Path

from tools.req001.actions import ActionResult, execute_action
from tools.req001.ai_runner import run_scenario
from tools.req001.bdd_parser import parse_gherkin
from tools.req001.exec_guards import (
    RepeatClickGuard,
    evaluate_calc_completion,
    extract_calc_expectation,
    hierarchy_fingerprint,
    recognized_result,
    resolve_click_target,
    score_click_candidate,
)
from tools.req001.llm_client import LlmConfig, OpenAICompatibleClient
from tools.req001.ui_observe import UiNode, parse_ui_hierarchy


# Layout taken from the real failed S2 dump (device 719c3b82): the display
# EditText shows "1" at center (540, 435); the key "1" is a compact View.
REAL_S2_XML = """<?xml version='1.0' encoding='UTF-8'?>
<hierarchy>
  <node class="android.widget.FrameLayout" bounds="[0,0][1080,2347]" resource-id="android:id/content">
    <node text="DEG" content-desc="DEG" clickable="true" class="android.widget.Button" bounds="[45,139][225,274]"/>
    <node text="1" clickable="true" class="android.widget.EditText" bounds="[0,286][1080,584]"/>
    <node content-desc="C" clickable="true" class="android.view.View" bounds="[0,1059][253,1316]"/>
    <node content-desc="7" clickable="true" class="android.view.View" bounds="[0,1316][253,1574]"/>
    <node content-desc="4" clickable="true" class="android.view.View" bounds="[0,1574][253,1832]"/>
    <node content-desc="1" clickable="true" class="android.view.View" bounds="[0,1832][253,2089]"/>
    <node content-desc="+" clickable="true" class="android.view.View" bounds="[759,1832][1013,2089]"/>
    <node content-desc="=" clickable="true" class="android.view.View" bounds="[759,2089][1013,2347]"/>
  </node>
</hierarchy>
"""

CALC_FEATURE = """
功能: 成功计算路径
  场景: REQ-001-S2 计算 1+1 等于 2
    假如 被测应用已在前台
    当 在被测应用中输入 1+1 并求出结果
    那么 界面上可以看到结果 2
"""

S3_FEATURE = """
功能: 失败断言路径
  场景: REQ-001-S3 计算 1+1 断言等于 3
    假如 被测应用已在前台
    当 在被测应用中输入 1+1 并求出结果
    那么 界面上可以看到结果 3
"""

KEY_1 = (126, 1960)  # center of content-desc 1 key
DISPLAY_1 = (540, 435)  # center of EditText display


def _nodes():
    return parse_ui_hierarchy(REAL_S2_XML)


def _client(script):
    def completer(messages, temperature=0.0):
        return script.pop(0) if script else json.dumps({"action": "fail", "reason": "script exhausted"})

    return OpenAICompatibleClient(
        LlmConfig(api_key="dummy", base_url="http://example.invalid/v1", model="dummy"),
        completer=completer,
    )


def test_click_prefers_key_content_desc_over_display_text():
    nodes = _nodes()
    target = resolve_click_target({"action": "click", "text": "1"}, nodes)
    assert target is not None
    assert (target.x, target.y) == KEY_1
    assert target.source in {"content_desc", "text"}
    # Guessed display coordinates must not win when the key exists.
    guessed = resolve_click_target({"action": "click", "text": "1", "x": 540, "y": 435}, nodes)
    assert guessed is not None
    assert (guessed.x, guessed.y) == KEY_1
    plus = resolve_click_target({"action": "click", "content_desc": "+"}, nodes)
    assert plus is not None
    assert (plus.x, plus.y) == (886, 1960)


def test_display_candidate_scores_below_key():
    nodes = _nodes()
    display = next(n for n in nodes if n.text == "1" and "EditText" in n.class_name)
    key = next(n for n in nodes if n.content_desc == "1")
    assert score_click_candidate(key, "1", 1080) > score_click_candidate(display, "1", 1080)


def test_execute_click_uses_key_not_guessed_xy(monkeypatch):
    tapped = []

    def fake_tap(adb, serial, x, y):
        tapped.append((x, y))

    monkeypatch.setattr("tools.req001.actions._tap", fake_tap)
    result = execute_action(
        {"action": "click", "text": "1", "x": 540, "y": 435},
        adb=Path("adb"),
        serial="719c3b82",
        app_package="io.dahliaos.calculator",
        nodes=_nodes(),
    )
    assert result.ok
    assert tapped == [KEY_1]
    assert result.click_xy == KEY_1
    assert "「1」" in result.message


def test_repeat_click_blocked_when_screen_unchanged():
    guard = RepeatClickGuard()
    fp = "display=1"
    guard.observe(fp)
    assert not guard.blocks(DISPLAY_1)
    guard.record_click(DISPLAY_1)
    # Same hierarchy after the click: the display click did nothing.
    guard.observe(fp)
    assert guard.blocks(DISPLAY_1)
    assert not guard.blocks(KEY_1)
    assert "拒绝重复点击同一坐标 (540,435)" in guard.reject_message(DISPLAY_1)


def test_same_key_allowed_again_after_screen_changes():
    guard = RepeatClickGuard()
    guard.observe("display=")
    guard.record_click(KEY_1)
    guard.observe("display=1")
    assert not guard.blocks(KEY_1)


def test_runner_rejects_spinning_same_coordinate_clicks(tmp_path):
    shot = tmp_path / "s.png"
    shot.write_bytes(b"png")
    nodes = _nodes()
    compact = []
    # Given done, then the model keeps proposing the display coordinates for "1".
    script = [
        json.dumps({"action": "step_done"}),  # given
        json.dumps({"action": "click", "text": "1", "x": 540, "y": 435}),
        json.dumps({"action": "click", "text": "1", "x": 540, "y": 435}),
        json.dumps({"action": "click", "text": "+"}),
        json.dumps({"action": "step_done"}),
        json.dumps({"action": "step_done"}),
    ]
    executed = []

    def dump():
        return nodes, shot, compact

    def exec_fn(action, _nodes):
        executed.append((action.get("action"), action.get("x"), action.get("y"), action.get("text") or action.get("content_desc")))
        if action["action"] == "step_done":
            return ActionResult(ok=True, step_done=True, message="done")
        target = resolve_click_target(action, _nodes)
        xy = (target.x, target.y) if target else None
        return ActionResult(ok=True, message=f"点击「{action.get('text') or action.get('content_desc')}」{xy}", click_xy=xy)

    result = run_scenario(
        parse_gherkin(CALC_FEATURE).scenarios[0],
        app_package="io.dahliaos.calculator",
        client=_client(script),
        dump_fn=dump,
        exec_fn=exec_fn,
        max_steps=20,
    )
    click_payloads = [item for item in executed if item[0] == "click"]
    # First click is executed (resolved to the key); the repeated display-coord proposal is blocked.
    assert click_payloads[0][0] == "click"
    assert any("拒绝重复点击同一坐标" in step for step in result.steps)
    assert sum(1 for item in click_payloads if item[3] == "1") == 1
    # Plus is a different target and must still be executed.
    assert any(item[3] == "+" for item in click_payloads)
    assert result.status == "pass"


def test_extract_and_recognize_expression_result():
    scenario = parse_gherkin(CALC_FEATURE).scenarios[0]
    exp = extract_calc_expectation(scenario)
    assert exp is not None
    assert exp.expression == "1+1"
    assert exp.expected_result == "2"
    s3 = extract_calc_expectation(parse_gherkin(S3_FEATURE).scenarios[0])
    assert s3 is not None and s3.expected_result == "3"

    display_done = [
        UiNode(text="1+1=2", class_name="android.widget.EditText", clickable=True, bounds=[0, 286, 1080, 584])
    ]
    assert recognized_result(display_done, "1+1", history=[]) == "2"

    display_two = [
        UiNode(text="2", class_name="android.widget.EditText", clickable=True, bounds=[0, 286, 1080, 584])
    ]
    history = [
        "when 输入 -> click: 点击「1」(126,1960)",
        "when 输入 -> click: 点击「+」(886,1960)",
        "when 输入 -> click: 点击「1」(126,1960)",
        "when 输入 -> click: 点击「=」(886,2218)",
    ]
    assert recognized_result(display_two, "1+1", history=history) == "2"
    # Without equals in history, a lone "2" is not a completed 1+1.
    assert recognized_result(display_two, "1+1", history=history[:3]) is None


def test_runner_ends_early_when_expression_and_result_visible(tmp_path):
    shot = tmp_path / "s.png"
    shot.write_bytes(b"png")
    given_nodes = [
        UiNode(text="", content_desc="1", clickable=True, class_name="android.view.View", bounds=[0, 1832, 253, 2089])
    ]
    done_nodes = [
        UiNode(text="1+1=2", class_name="android.widget.EditText", clickable=True, bounds=[0, 286, 1080, 584]),
        UiNode(text="", content_desc="1", clickable=True, class_name="android.view.View", bounds=[0, 1832, 253, 2089]),
        UiNode(text="", content_desc="=", clickable=True, class_name="android.view.View", bounds=[759, 2089, 1013, 2347]),
    ]
    state = {"phase": "given"}
    llm_calls = {"n": 0}

    def dump():
        if state["phase"] == "given":
            return given_nodes, shot, []
        return done_nodes, shot, []

    def completer(messages, temperature=0.0):
        llm_calls["n"] += 1
        # Only the Given step needs the model; When/Then should auto-finish.
        return json.dumps({"action": "step_done"})

    client = OpenAICompatibleClient(
        LlmConfig(api_key="dummy", base_url="http://example.invalid/v1", model="dummy"),
        completer=completer,
    )

    def exec_fn(action, nodes):
        if action["action"] == "step_done":
            state["phase"] = "done"
            return ActionResult(ok=True, step_done=True, message="done")
        return ActionResult(ok=True, message="ok")

    result = run_scenario(
        parse_gherkin(CALC_FEATURE).scenarios[0],
        app_package="io.dahliaos.calculator",
        client=client,
        dump_fn=dump,
        exec_fn=exec_fn,
        max_steps=20,
    )
    assert result.status == "pass"
    assert llm_calls["n"] == 1
    assert any("提前结束" in step for step in result.steps)
    # Must not burn the remaining step budget.
    assert len([s for s in result.steps if "最大步数" in s]) == 0


def _calc_keys(display_text=""):
    return [
        UiNode(text=display_text, class_name="android.widget.EditText", clickable=True, bounds=[0, 286, 1080, 584]),
        UiNode(text="", content_desc="1", clickable=True, class_name="android.view.View", bounds=[0, 1832, 253, 2089]),
        UiNode(text="", content_desc="+", clickable=True, class_name="android.view.View", bounds=[759, 1832, 1013, 2089]),
        UiNode(text="", content_desc="=", clickable=True, class_name="android.view.View", bounds=[759, 2089, 1013, 2347]),
    ]


def test_runner_fails_s3_promptly_after_recognizing_result_2(tmp_path):
    shot = tmp_path / "s.png"
    shot.write_bytes(b"png")
    state = {"display": ""}

    def dump():
        return _calc_keys(state["display"]), shot, []

    script = [
        json.dumps({"action": "step_done"}),  # given
        json.dumps({"action": "click", "text": "1"}),
        json.dumps({"action": "click", "content_desc": "+"}),
        json.dumps({"action": "click", "text": "1"}),
        json.dumps({"action": "click", "content_desc": "="}),
        # If the guard failed, the model would keep walking the step budget.
        json.dumps({"action": "wait", "seconds": 0}),
        json.dumps({"action": "wait", "seconds": 0}),
    ]

    def exec_fn(action, nodes):
        if action["action"] == "step_done":
            return ActionResult(ok=True, step_done=True, message="done")
        label = action.get("text") or action.get("content_desc") or ""
        if action["action"] == "click":
            if label == "1":
                state["display"] = "1" if state["display"] in {"", "0"} else (
                    "1+1" if state["display"] in {"1+", "1 +"} else state["display"] + "1"
                )
            elif label in {"+", "＋"}:
                state["display"] = (state["display"] or "") + "+"
            elif label in {"=", "＝"}:
                state["display"] = "2"
        target = resolve_click_target(action, nodes) if action["action"] == "click" else None
        xy = (target.x, target.y) if target else None
        return ActionResult(ok=True, message=f"点击「{label}」({xy[0] if xy else 0},{xy[1] if xy else 0})", click_xy=xy)

    result = run_scenario(
        parse_gherkin(S3_FEATURE).scenarios[0],
        app_package="io.dahliaos.calculator",
        client=_client(script),
        dump_fn=dump,
        exec_fn=exec_fn,
        max_steps=20,
    )
    assert result.status == "fail"
    assert "实际结果为「2」" in result.failure_reason
    assert "期望看到「3」" in result.failure_reason
    assert "最大步数" not in result.failure_reason
    # No leftover wait actions after the result was recognized.
    assert all("wait" not in step for step in result.steps)


def test_hierarchy_fingerprint_changes_with_display_text():
    before = [UiNode(text="", class_name="android.widget.EditText", bounds=[0, 286, 1080, 584])]
    after = [UiNode(text="1", class_name="android.widget.EditText", bounds=[0, 286, 1080, 584])]
    assert hierarchy_fingerprint(before) != hierarchy_fingerprint(after)


def test_evaluate_completion_none_for_non_calc_case():
    feature = """
功能: 打开
  场景: REQ-001-S1 打开被测应用
    假如 被测应用已安装
    当 启动被测应用
    那么 被测应用进入前台
"""
    scenario = parse_gherkin(feature).scenarios[0]
    assert extract_calc_expectation(scenario) is None
    decision = evaluate_calc_completion(scenario, scenario.steps[0], _nodes(), [])
    assert decision.kind == "none"

# -*- coding: utf-8 -*-
from tools.req001.bdd_parser import parse_gherkin
from tools.req001.keypad import (
    KEYPAD_MISSING_HINT,
    ensure_keypad_ready,
    keypad_is_visible,
    scenario_needs_keypad,
)
from tools.req001.ui_observe import UiNode


def _nodes(*labels):
    return [
        UiNode(text="", content_desc=label, clickable=True, bounds=[0, 0, 10, 10])
        for label in labels
    ]


def test_keypad_visible_when_required_keys_present():
    assert keypad_is_visible(_nodes("DEG", "C", "1", "2", "+", "=")) is True


def test_keypad_hidden_when_only_deg():
    assert keypad_is_visible(_nodes("DEG")) is False
    assert keypad_is_visible([]) is False


def test_scenario_needs_keypad_for_s2_s3_not_s1():
    features = {
        "s1": parse_gherkin(
            "功能: 打开\n  场景: REQ-001-S1 打开被测应用\n    假如 被测应用已安装\n    当 启动被测应用\n    那么 被测应用进入前台\n"
        ),
        "s2": parse_gherkin(
            "功能: 成功\n  场景: REQ-001-S2 计算 1+1 等于 2\n    假如 被测应用已在前台\n    当 输入 1+1\n    那么 结果等于 2\n"
        ),
        "s3": parse_gherkin(
            "功能: 失败\n  场景: REQ-001-S3 计算 1+1 断言等于 3\n    假如 被测应用已在前台\n    当 输入 1+1\n    那么 结果等于 3\n"
        ),
    }
    assert scenario_needs_keypad(features["s1"].scenarios[0]) is False
    assert scenario_needs_keypad(features["s2"].scenarios[0]) is True
    assert scenario_needs_keypad(features["s3"].scenarios[0]) is True


def test_ensure_keypad_ok_without_recovery():
    def dump():
        return _nodes("1", "+", "=")

    result = ensure_keypad_ready(dump)
    assert result.visible is True
    assert result.recovered_by == ""


def test_ensure_keypad_relaunches_app_when_blank():
    state = {"relaunched": False}

    def dump():
        if not state["relaunched"]:
            return _nodes("DEG")
        return _nodes("1", "+", "=")

    relaunched = {"ok": False}

    def relaunch():
        state["relaunched"] = True
        relaunched["ok"] = True

    result = ensure_keypad_ready(dump, relaunch_fn=relaunch, reboot_fn=lambda: (_ for _ in ()).throw(AssertionError("reboot should not run")), sleep_fn=lambda _seconds: None)
    assert relaunched["ok"] is True
    assert result.visible is True
    assert result.recovered_by == "app_relaunch"


def test_ensure_keypad_reboots_emulator_if_relaunch_not_enough():
    calls = []

    def dump():
        if "emu" in calls:
            return _nodes("1", "+", "=")
        return _nodes("DEG")

    result = ensure_keypad_ready(
        dump,
        relaunch_fn=lambda: calls.append("app"),
        reboot_fn=lambda: calls.append("emu"),
        sleep_fn=lambda _seconds: None,
    )
    assert calls == ["app", "emu"]
    assert result.visible is True
    assert result.recovered_by == "emulator_reboot"


def test_ensure_keypad_gives_clear_hint_when_still_blank():
    result = ensure_keypad_ready(
        lambda: _nodes("DEG"),
        relaunch_fn=lambda: None,
        reboot_fn=lambda: None,
        sleep_fn=lambda _seconds: None,
    )
    assert result.visible is False
    assert "重启模拟器" in result.message
    assert result.message == KEYPAD_MISSING_HINT

def test_ensure_keypad_hint_omits_emulator_reboot_when_reboot_forbidden():
    result = ensure_keypad_ready(
        lambda: _nodes("DEG"),
        relaunch_fn=lambda: None,
        reboot_fn=None,
        sleep_fn=lambda _seconds: None,
    )
    assert result.visible is False
    assert "重启模拟器" not in result.message
    assert "键区" in result.message


def test_ensure_keypad_hint_omits_emulator_reboot_for_physical_device():
    result = ensure_keypad_ready(
        lambda: _nodes("DEG"),
        relaunch_fn=lambda: None,
        reboot_fn=lambda: None,
        is_emulator=False,
        sleep_fn=lambda _seconds: None,
    )
    assert result.visible is False
    assert "重启模拟器" not in result.message
    assert "键区" in result.message


def test_ensure_keypad_retries_blank_render_before_relaunch():
    state = {"n": 0}

    def dump():
        state["n"] += 1
        if state["n"] < 3:
            return _nodes("DEG")
        return _nodes("1", "+", "=")

    relaunched = {"ok": False}

    def relaunch():
        relaunched["ok"] = True
        raise AssertionError("relaunch should wait for late keypad render")

    result = ensure_keypad_ready(dump, relaunch_fn=relaunch, reboot_fn=None, sleep_fn=lambda _seconds: None)
    assert result.visible is True
    assert relaunched["ok"] is False
    assert state["n"] == 3
    assert result.recovered_by in {"", "retry"}


def test_ensure_keypad_retries_after_relaunch_for_late_render():
    state = {"n": 0, "relaunched": False, "after": 0}

    def dump():
        state["n"] += 1
        if not state["relaunched"]:
            return _nodes("DEG")
        # First dump after relaunch is still blank (orientation / render lag).
        if state["after"] == 0:
            state["after"] += 1
            return _nodes("DEG")
        return _nodes("1", "+", "=")

    def relaunch():
        state["relaunched"] = True

    result = ensure_keypad_ready(
        dump,
        relaunch_fn=relaunch,
        reboot_fn=lambda: (_ for _ in ()).throw(AssertionError("reboot should not run")),
        sleep_fn=lambda _seconds: None,
    )
    assert state["relaunched"] is True
    assert result.visible is True
    assert result.recovered_by == "app_relaunch"

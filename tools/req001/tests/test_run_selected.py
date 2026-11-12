# -*- coding: utf-8 -*-
"""Unit tests for the REQ-002 run_selected adapter (no real device or live LLM)."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import tools.req001.run_selected as adapter
from tools.req001.adb_utils import AdbDevice
from tools.req001.html_report import CaseResult
from tools.req001.keypad import KeypadReady
from tools.req001.llm_client import LlmConfig, OpenAICompatibleClient
from tools.req001.run_selected import run_selected


def _feature(tmp_path: Path, name: str = "demo.feature") -> Path:
    path = tmp_path / name
    path.write_text(
        "# language: zh-CN\n"
        "功能: 演示\n"
        "  场景: REQ-001-S2 成功路径\n"
        "    假如 已打开应用\n"
        "    当 执行计算\n"
        "    那么 结果正确\n",
        encoding="utf-8",
    )
    return path


def _s3_feature(tmp_path: Path) -> Path:
    path = tmp_path / "REQ-001-S3_wrong_assertion.feature"
    path.write_text(
        "# language: zh-CN\n"
        "功能: 失败断言\n"
        "  场景: REQ-001-S3 故意断言 1+1 等于 3\n"
        "    假如 已打开应用\n"
        "    当 计算 1+1\n"
        "    那么 结果等于 3\n",
        encoding="utf-8",
    )
    return path


def _online(serial: str = "emulator-5554") -> list:
    return [AdbDevice(serial=serial, state="device")]


def _client():
    cfg = LlmConfig(api_key="test-key", base_url="http://example.invalid/v1", model="mock")
    return OpenAICompatibleClient(cfg, completer=lambda **kwargs: '{"action":"step_done"}')


def _app():
    return SimpleNamespace(package="com.example.calc", source="preinstalled_calculator", notes=["ok"])


def test_adapter_source_does_not_call_ensure_emulator_or_wrap_run_mvp():
    source = Path(__file__).resolve().parents[1] / "run_selected.py"
    text = source.read_text(encoding="utf-8")
    assert "ensure_emulator(" not in text and "from tools.req001.emulator" not in text
    assert "import run_mvp" not in text and "from tools.req001.run_mvp" not in text and "run_mvp(" not in text
    assert "import scrcpy" not in text.lower() and "scrcpy(" not in text.lower()
    assert "execute_app_test_task" not in text
    assert "allure" not in text.lower()


def test_offline_device_fails_without_starting_emulator(tmp_path, monkeypatch):
    called = {"ensure": 0}

    def boom(*args, **kwargs):
        called["ensure"] += 1
        raise AssertionError("ensure_emulator must not be called")

    monkeypatch.setattr("tools.req001.emulator.ensure_emulator", boom, raising=False)
    result = run_selected(
        "emulator-5554",
        [_feature(tmp_path)],
        tmp_path / "out",
        list_devices_fn=lambda: [AdbDevice(serial="emulator-5554", state="offline")],
        llm_client=_client(),
    )
    assert result.ok is False
    assert result.message == adapter.DEVICE_OFFLINE_MESSAGE
    assert "api" not in result.message.lower()
    assert "C:\\" not in result.message
    assert called["ensure"] == 0
    assert result.report_index is None


def test_missing_device_fails_safely(tmp_path):
    result = run_selected(
        "emulator-5554",
        [_feature(tmp_path)],
        tmp_path / "out",
        list_devices_fn=lambda: [],
        llm_client=_client(),
    )
    assert result.ok is False
    assert result.message == adapter.DEVICE_OFFLINE_MESSAGE


def test_missing_llm_returns_tester_safe_message(tmp_path):
    from tools.req001.errors import LlmConfigError

    def bad_loader():
        raise LlmConfigError("缺少 DASHSCOPE_API_KEY。C:\\\\Users\\\\EmmaLiu\\\\.commit-review.env")

    result = run_selected(
        "emulator-5554",
        [_feature(tmp_path)],
        tmp_path / "out",
        list_devices_fn=lambda: _online(),
        load_llm_fn=bad_loader,
        adb=Path("adb"),
    )
    assert result.ok is False
    assert result.message == adapter.LLM_NOT_CONFIGURED_MESSAGE
    assert "DASHSCOPE" not in result.message
    assert "commit-review" not in result.message
    assert "Users" not in result.message


def test_fixture_assertion_failure_still_writes_report(tmp_path):
    shot = tmp_path / "raw.png"
    shot.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 16)

    def fake_run(scenario, **kwargs):
        return CaseResult(
            case_id=scenario.case_id,
            name=scenario.name,
            status="pass",
            failure_reason="",
            screenshots=[str(shot)],
        )

    result = run_selected(
        "emulator-5554",
        [_s3_feature(tmp_path)],
        tmp_path / "out",
        list_devices_fn=lambda: _online(),
        llm_client=_client(),
        adb=Path("adb"),
        resolve_app_fn=lambda shell: _app(),
        run_scenario_fn=fake_run,
        keypad_check_fn=lambda *a, **k: KeypadReady(True, "", "ok"),
    )
    assert result.ok is True
    assert result.report_index is not None and result.report_index.is_file()
    assert (tmp_path / "out" / "index.html").is_file()
    assert len(result.cases) == 1
    assert result.cases[0].status == "fail"
    assert result.cases[0].failure_reason
    html = result.report_index.read_text(encoding="utf-8")
    assert "REQ-001-S3" in html
    assert "失败" in html


def test_successful_fixture_writes_report_with_screenshot(tmp_path):
    shot = tmp_path / "ok.png"
    shot.write_bytes(b"\x89PNG\r\n\x1a\n" + b"1" * 16)

    def fake_run(scenario, **kwargs):
        return CaseResult(
            case_id=scenario.case_id,
            name=scenario.name,
            status="pass",
            screenshots=[str(shot)],
        )

    result = run_selected(
        "emulator-5554",
        [_feature(tmp_path)],
        tmp_path / "out",
        list_devices_fn=lambda: _online(),
        llm_client=_client(),
        adb=Path("adb"),
        resolve_app_fn=lambda shell: _app(),
        run_scenario_fn=fake_run,
        keypad_check_fn=lambda *a, **k: KeypadReady(True, "", "ok"),
    )
    assert result.ok is True
    assert result.cases[0].status == "pass"
    assert result.cases[0].screenshots
    assert all(not Path(s).is_absolute() for s in result.cases[0].screenshots)
    assert "screenshots/" in result.cases[0].screenshots[0]

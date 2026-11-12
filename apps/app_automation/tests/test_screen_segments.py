import os

import pytest
from apps.app_automation.recording.adb_gateway import (
    adb_executable,
    crop_fraction,
    ensure_adb_on_path,
    safe_device_filename,
)
from apps.app_automation.recording.replay import ScreenRecordError
from apps.app_automation.runners.event_chain_runner import (
    AdbEventDevice,
    clear_field_commands,
    input_text_command,
    segment_count,
)


def test_adb_executable_uses_sdk_when_command_is_missing(monkeypatch, tmp_path):
    adb = tmp_path / "platform-tools" / "adb.exe"
    adb.parent.mkdir()
    adb.write_bytes(b"")
    monkeypatch.setattr(
        "apps.app_automation.recording.adb_gateway._configured_adb_path",
        lambda: "",
    )
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setenv("ANDROID_HOME", str(tmp_path))
    monkeypatch.delenv("ANDROID_SDK_ROOT", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert adb_executable() == str(adb)


def test_ensure_adb_on_path_prepends_platform_tools(monkeypatch, tmp_path):
    adb = tmp_path / "platform-tools" / "adb.exe"
    adb.parent.mkdir()
    adb.write_bytes(b"")
    monkeypatch.setattr(
        "apps.app_automation.recording.adb_gateway.adb_executable",
        lambda: str(adb),
    )
    monkeypatch.setenv("PATH", r"C:\Windows")
    assert ensure_adb_on_path() == str(adb)
    assert os.environ["PATH"].split(os.pathsep)[0] == str(adb.parent)


def test_safe_device_filename():
    assert safe_device_filename("192.168.1.8:5555") == "192.168.1.8_5555"
    assert safe_device_filename("emulator-5554") == "emulator-5554"


def test_segment_count_splits_at_180_seconds():
    assert segment_count(0) == 0
    assert segment_count(1) == 1
    assert segment_count(180) == 1
    assert segment_count(181) == 2
    assert segment_count(360) == 2


def test_crop_fraction_scales_bounds_on_a_fake_image():
    try:
        import cv2
        import numpy as np
    except ImportError:
        pytest.importorskip("PIL")
        from PIL import Image
        image = Image.new("RGB", (200, 100), (9, 9, 9))
        for y in range(20, 40):
            for x in range(50, 90):
                image.putpixel((x, y), (1, 2, 3))
        cropped = crop_fraction(image, {"x": 0.25, "y": 0.2, "w": 0.2, "h": 0.2})
        assert cropped.size == (40, 20)
        assert cropped.getpixel((0, 0)) == (1, 2, 3)
        return
    image = np.zeros((100, 200, 3), dtype=np.uint8)
    image[:, :] = (9, 9, 9)
    image[20:40, 50:90] = (1, 2, 3)
    cropped = crop_fraction(image, {"x": 0.25, "y": 0.2, "w": 0.2, "h": 0.2})
    assert cropped.shape[:2] == (20, 40)
    assert tuple(int(value) for value in cropped[0, 0]) == (1, 2, 3)


def test_input_text_command_keeps_text_as_one_argv():
    command = input_text_command("emulator-5554", "你好 world;rm")
    assert command[-1] == "你好 world;rm"
    assert command.count("你好 world;rm") == 1
    assert clear_field_commands("emulator-5554")[1][-3:] == ["keycombination", "113", "29"]


def test_input_text_clears_then_uses_airtest_without_shelling_text(monkeypatch):
    import apps.app_automation.runners.event_chain_runner as runner
    calls = []
    monkeypatch.setattr(runner.subprocess, "check_call", lambda args: calls.append(list(args)))
    written = {}
    monkeypatch.setattr(
        runner, "write_with_airtest",
        lambda device_id, value: written.update(device_id=device_id, value=value),
    )
    device = AdbEventDevice("emulator-5554", "exec-1")
    device._size = (1080, 1920)
    device.input_text({"bounds": {"x": 0, "y": 0, "w": 0.2, "h": 0.1}}, "你好 world")
    assert written == {"device_id": "emulator-5554", "value": "你好 world"}
    assert all("你好 world" not in arg for command in calls for arg in command)
    assert any("KEYCODE_DEL" in command for command in calls)
    assert any("keycombination" in command for command in calls)


def test_input_text_falls_back_to_one_argv_when_airtest_missing(monkeypatch):
    import apps.app_automation.runners.event_chain_runner as runner
    calls = []
    monkeypatch.setattr(runner.subprocess, "check_call", lambda args: calls.append(list(args)))
    monkeypatch.setattr(runner, "airtest_text_writer", lambda: None)
    device = AdbEventDevice("emulator-5554", "exec-1")
    device._size = (1080, 1920)
    device.input_text({"bounds": {"x": 0, "y": 0, "w": 1, "h": 1}}, "你好 world")
    assert calls[-1] == input_text_command("emulator-5554", "你好 world")
    assert calls[-1][-1] == "你好 world"


def test_write_with_airtest_passes_text_as_one_argument(monkeypatch):
    from airtest.core import api as airtest_api
    import apps.app_automation.runners.event_chain_runner as runner
    seen = {}
    monkeypatch.setattr(
        airtest_api, "text",
        lambda value, enter=True, **kwargs: seen.update(value=value, enter=enter),
    )
    monkeypatch.setattr(airtest_api, "connect_device", lambda uri: seen.update(uri=uri))
    runner.write_with_airtest("emulator-5554", "你好")
    assert seen["value"] == "你好"
    assert seen["enter"] is False
    assert seen["uri"] == "Android:///emulator-5554"


def test_stop_screenrecord_raises_without_returning_partial_videos():
    device = AdbEventDevice("emulator-5554", "exec-1")
    device._videos = ["video-1.mp4"]
    device._record_error = "录屏失败"
    with pytest.raises(ScreenRecordError, match="录屏失败"):
        device.stop_screenrecord()
    assert device._videos == ["video-1.mp4"]

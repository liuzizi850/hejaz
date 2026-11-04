import pytest
from apps.app_automation.recording.adb_gateway import safe_device_filename
from apps.app_automation.recording.replay import ScreenRecordError
from apps.app_automation.runners.event_chain_runner import AdbEventDevice, segment_count


def test_safe_device_filename():
    assert safe_device_filename("192.168.1.8:5555") == "192.168.1.8_5555"
    assert safe_device_filename("emulator-5554") == "emulator-5554"


def test_segment_count_splits_at_180_seconds():
    assert segment_count(0) == 0
    assert segment_count(1) == 1
    assert segment_count(180) == 1
    assert segment_count(181) == 2
    assert segment_count(360) == 2


def test_stop_screenrecord_raises_without_returning_partial_videos():
    device = AdbEventDevice("emulator-5554", "exec-1")
    device._videos = ["video-1.mp4"]
    device._record_error = "录屏失败"
    with pytest.raises(ScreenRecordError, match="录屏失败"):
        device.stop_screenrecord()
    assert device._videos == ["video-1.mp4"]

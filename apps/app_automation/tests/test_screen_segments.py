from apps.app_automation.recording.adb_gateway import safe_device_filename
from apps.app_automation.runners.event_chain_runner import segment_count


def test_safe_device_filename():
    assert safe_device_filename("192.168.1.8:5555") == "192.168.1.8_5555"
    assert safe_device_filename("emulator-5554") == "emulator-5554"


def test_segment_count_splits_at_180_seconds():
    assert segment_count(0) == 0
    assert segment_count(1) == 1
    assert segment_count(180) == 1
    assert segment_count(181) == 2
    assert segment_count(360) == 2

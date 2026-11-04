import pytest
from apps.app_automation.recording.replay import replay_event_chain, ScreenRecordError

class FakeDevice:
    def __init__(self, match=True, nodes=None, template=False, record_ok=True, stop_ok=True):
        self.match = match
        self.nodes = nodes or []
        self.template = template
        self.record_ok = record_ok
        self.stop_ok = stop_ok
        self.calls = []

    def screenshot(self, name):
        self.calls.append(("screenshot", name))
        return name + ".png"

    def match_images(self, expected, actual, crop_top_ratio):
        self.calls.append(("match", crop_top_ratio))
        return self.match

    def find_nodes(self):
        return self.nodes

    def match_template(self, path):
        self.calls.append(("template", path))
        return self.template

    def click(self, node):
        self.calls.append(("click", node.get("resource_id")))

    def long_press(self, node, duration_ms):
        self.calls.append(("long_press", duration_ms))

    def swipe(self, node, direction, distance):
        self.calls.append(("swipe", direction, distance))

    def input_text(self, node, text):
        self.calls.append(("input", text))

    def wait_ms(self, duration_ms):
        self.calls.append(("wait", duration_ms))

    def text_exists(self, text):
        return text == "欢迎"

    def selector_exists(self, selector):
        return False

    def start_screenrecord(self):
        if not self.record_ok:
            raise ScreenRecordError("录屏失败")
        self.calls.append(("start_record",))

    def stop_screenrecord(self):
        if not self.stop_ok:
            raise ScreenRecordError("录屏失败")
        self.calls.append(("stop_record",))
        return ["video-1.mp4"]


def test_mismatch_does_not_record():
    device = FakeDevice(match=False)
    result = replay_event_chain([{"type": "click", "order": 1, "name": "点", "resource_id": "a"}], "start.png", device)
    assert result["start_screen_mismatch"] is True
    assert result["passed"] is False
    assert result["videos"] == []
    assert ("start_record",) not in device.calls
    assert device.calls[1] == ("match", 0.08)


def test_click_uses_identity_then_stops_on_next_failure():
    device = FakeDevice(nodes=[{"resource_id": "ok", "bounds": {"x": 0, "y": 0, "w": 0.1, "h": 0.1}}])
    steps = [
        {"type": "click", "order": 1, "name": "点确定", "resource_id": "ok", "bounds": {"x": 0, "y": 0, "w": 0.1, "h": 0.1}},
        {"type": "click", "order": 2, "name": "点缺失", "resource_id": "missing"},
        {"type": "wait", "order": 3, "name": "等待", "duration_ms": 500},
    ]
    result = replay_event_chain(steps, "start.png", device)
    assert result["passed"] is False
    assert [item["status"] for item in result["steps"]] == ["passed", "failed", "skipped"]
    assert result["steps"][2]["reason"] == "未执行"
    assert result["videos"] == ["video-1.mp4"]


def test_empty_input_fails_without_typing():
    device = FakeDevice(nodes=[{"resource_id": "pwd"}])
    result = replay_event_chain(
        [{"type": "input", "order": 1, "name": "密码", "resource_id": "pwd", "input_text": ""}],
        "start.png",
        device,
    )
    assert result["steps"][0]["status"] == "failed"
    assert ("input", "") not in device.calls


def test_template_fallback_clicks():
    device = FakeDevice(nodes=[], template=True)
    result = replay_event_chain(
        [{"type": "click", "order": 1, "name": "图标", "template": "icon.png"}],
        "start.png",
        device,
    )
    assert result["passed"] is True
    assert ("template", "icon.png") in device.calls


def test_assert_text_and_screenrecord_error_still_runs_steps():
    device = FakeDevice(record_ok=False)
    result = replay_event_chain(
        [{"type": "assert", "order": 1, "name": "欢迎语", "expected_texts": ["欢迎"], "expected_selectors": []}],
        "start.png",
        device,
    )
    assert result["screenrecord_error"] == "录屏失败"
    assert result["videos"] == []
    assert result["steps"][0]["status"] == "passed"


def test_two_click_steps_keep_separate_ordered_screenshots():
    device = FakeDevice(nodes=[
        {"resource_id": "ok", "bounds": {"x": 0, "y": 0, "w": 0.1, "h": 0.1}},
        {"resource_id": "next", "bounds": {"x": 0.2, "y": 0.2, "w": 0.1, "h": 0.1}},
    ])
    result = replay_event_chain(
        [
            {"type": "click", "order": 1, "name": "点确定", "resource_id": "ok"},
            {"type": "click", "order": 2, "name": "点下一步", "resource_id": "next"},
        ],
        "start.png",
        device,
    )
    first, second = result["steps"][0]["screenshot"], result["steps"][1]["screenshot"]
    assert first != second
    assert "1" in first
    assert "2" in second


def test_stop_screenrecord_error_keeps_steps_and_drops_videos():
    device = FakeDevice(
        nodes=[{"resource_id": "ok", "bounds": {"x": 0, "y": 0, "w": 0.1, "h": 0.1}}],
        stop_ok=False,
    )
    result = replay_event_chain(
        [
            {"type": "click", "order": 1, "name": "点确定", "resource_id": "ok"},
            {"type": "click", "order": 2, "name": "点缺失", "resource_id": "missing"},
        ],
        "start.png",
        device,
    )
    assert [item["status"] for item in result["steps"]] == ["passed", "failed"]
    assert result["videos"] == []
    assert result["screenrecord_error"] == "录屏失败"

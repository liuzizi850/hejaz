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
        self.calls.append(("click", node.get("resource_id") or node.get("text")))

    def long_press(self, node, duration_ms):
        self.calls.append(("long_press", duration_ms))

    def swipe(self, node, direction, distance):
        self.calls.append(("swipe", direction, distance))

    def tap_point(self, x, y):
        self.calls.append(("tap_point", x, y))

    def long_press_point(self, x, y, duration_ms):
        self.calls.append(("long_press_point", x, y, duration_ms))

    def swipe_points(self, from_x, from_y, to_x, to_y):
        self.calls.append(("swipe_points", from_x, from_y, to_x, to_y))

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


def test_named_click_finds_the_app_when_the_start_screen_differs():
    device = FakeDevice(
        match=False,
        nodes=[{"text": "wahda", "bounds": {"x": 0.2, "y": 0.1, "w": 0.2, "h": 0.1}}],
    )
    result = replay_event_chain(
        [{"type": "click", "order": 1, "name": "点击 wahda", "text": "wahda", "x": 0.9, "y": 0.9}],
        "start.png",
        device,
    )
    assert result["start_screen_mismatch"] is False
    assert result["steps"][0]["status"] == "passed"
    assert ("click", "wahda") in device.calls
    assert ("tap_point", 0.9, 0.9) not in device.calls
    assert ("start_record",) in device.calls


def test_launcher_icon_tap_must_leave_the_home_screen():
    device = FakeDevice(match=True, nodes=[{"text": "wahda", "bounds": {"x": 0.3, "y": 0.08, "w": 0.1, "h": 0.04}}])
    packages = iter(["com.miui.home", "com.miui.home"])
    device.foreground_package = lambda: next(packages)
    device.locate_icon = lambda start_screen, x, y: (0.4, 0.11)
    result = replay_event_chain(
        [
            {"type": "click", "order": 1, "name": "点击 wahda", "text": "wahda", "x": 0.4, "y": 0.11},
            {"type": "click", "order": 2, "name": "点击 Qibla", "text": "Qibla", "x": 0.16, "y": 0.31},
        ],
        "start.png",
        device,
    )
    assert result["passed"] is False
    assert [item["status"] for item in result["steps"]] == ["failed"]
    assert result["steps"][0]["reason"] == "没有打开 wahda"
    assert ("click", "wahda") in device.calls
    assert ("tap_point", 0.4, 0.11) not in device.calls


def test_missing_named_app_does_not_open_whatever_is_at_the_old_point():
    device = FakeDevice(match=True, nodes=[{"text": "文件管理", "bounds": {"x": 0.3, "y": 0.08, "w": 0.12, "h": 0.08}}])
    device.foreground_package = lambda: "com.miui.home"
    device.locate_icon = lambda start_screen, x, y: (0.4, 0.11)
    result = replay_event_chain(
        [{"type": "click", "order": 1, "name": "点击 wahda", "text": "wahda", "x": 0.4, "y": 0.11}],
        "start.png",
        device,
    )
    assert result["passed"] is False
    assert result["steps"][0]["reason"] == "没有点到 wahda"
    assert not any(call[0] == "tap_point" for call in device.calls)
    assert not any(call[0] == "click" for call in device.calls)


def test_launcher_icon_tap_passes_after_the_app_opens():
    device = FakeDevice(
        match=True,
        nodes=[{"text": "wahda", "bounds": {"x": 0.3, "y": 0.08, "w": 0.1, "h": 0.04}}],
    )
    packages = iter(["com.miui.home", "com.example.wahda"])
    device.foreground_package = lambda: next(packages)
    result = replay_event_chain(
        [{"type": "click", "order": 1, "name": "点击 wahda", "text": "wahda", "x": 0.35, "y": 0.1}],
        "start.png",
        device,
    )
    assert result["steps"][0]["status"] == "passed"
    assert ("click", "wahda") in device.calls
    assert ("wait", 1200) in device.calls


def test_click_uses_identity_then_continues_after_failure():
    device = FakeDevice(nodes=[{"resource_id": "ok", "bounds": {"x": 0, "y": 0, "w": 0.1, "h": 0.1}}])
    steps = [
        {"type": "click", "order": 1, "name": "点确定", "resource_id": "ok", "bounds": {"x": 0, "y": 0, "w": 0.1, "h": 0.1}},
        {"type": "click", "order": 2, "name": "点缺失", "resource_id": "missing"},
        {"type": "wait", "order": 3, "name": "等待", "duration_ms": 500},
    ]
    result = replay_event_chain(steps, "start.png", device)
    assert result["passed"] is False
    assert [item["status"] for item in result["steps"]] == ["passed", "failed", "passed"]
    assert result["steps"][1]["reason"] == "找不到控件"
    assert result["steps"][1]["screenshot"] == "2-click.png"
    assert result["steps"][2]["screenshot"] == "3-wait.png"
    assert result["steps"][2]["reason"] == ""
    assert ("wait", 500) in device.calls
    assert result["videos"] == ["video-1.mp4"]


def test_finger_swipe_replays_between_the_two_points():
    device = FakeDevice()
    result = replay_event_chain(
        [{
            "type": "swipe",
            "order": 1,
            "name": "滑动",
            "from_x": 0.2,
            "from_y": 0.8,
            "to_x": 0.2,
            "to_y": 0.3,
        }],
        "start.png",
        device,
    )
    assert result["steps"][0]["status"] == "passed"
    assert ("swipe_points", 0.2, 0.8, 0.2, 0.3) in device.calls
    assert not any(call[0] == "swipe" for call in device.calls)


def test_progress_advances_with_each_finished_step():
    device = FakeDevice()
    seen = []
    replay_event_chain(
        [
            {"type": "click", "order": 1, "name": "点击", "x": 0.2, "y": 0.3},
            {"type": "wait", "order": 2, "name": "等待", "duration_ms": 1},
        ],
        "start.png",
        device,
        on_step=lambda done, total: seen.append((done, total)),
    )
    assert seen == [(1, 2), (2, 2)]


def test_first_coordinate_click_follows_the_recorded_icon():
    device = FakeDevice(match=False)

    def locate_icon(start_screen, x, y):
        device.calls.append(("locate_icon", start_screen, x, y))
        return 0.62, 0.13

    device.locate_icon = locate_icon
    result = replay_event_chain(
        [
            {"type": "click", "order": 1, "name": "点击 39%,13%", "x": 0.3864, "y": 0.1321},
            {"type": "click", "order": 2, "name": "点击 66%,51%", "x": 0.66, "y": 0.51},
        ],
        "start.png",
        device,
    )
    assert result["start_screen_mismatch"] is False
    assert ("tap_point", 0.62, 0.13) in device.calls
    assert ("tap_point", 0.3864, 0.1321) not in device.calls
    assert ("tap_point", 0.66, 0.51) in device.calls


def test_missing_recorded_icon_does_not_tap_the_old_point():
    device = FakeDevice(match=True)
    device.locate_icon = lambda start_screen, x, y: None
    result = replay_event_chain(
        [{"type": "click", "order": 1, "name": "点击 39%,13%", "x": 0.39, "y": 0.13}],
        "start.png",
        device,
    )
    assert result["steps"][0]["status"] == "failed"
    assert result["steps"][0]["reason"] == "找不到这个应用"
    assert not any(call[0] == "tap_point" for call in device.calls)


def test_seek_opens_the_app_when_it_is_not_on_the_current_screen():
    device = FakeDevice(match=True)
    device.locate_icon = lambda start_screen, x, y: None

    def seek_icon(start_screen, x, y):
        device.calls.append(("seek_icon", start_screen, x, y))
        return 0.2, 0.3

    device.seek_icon = seek_icon
    result = replay_event_chain(
        [{"type": "click", "order": 1, "name": "点击 39%,13%", "x": 0.39, "y": 0.13}],
        "start.png",
        device,
    )
    assert result["steps"][0]["status"] == "passed"
    assert ("seek_icon", "start.png", 0.39, 0.13) in device.calls
    assert ("tap_point", 0.2, 0.3) in device.calls


def test_coordinate_click_taps_without_a_control():
    device = FakeDevice()
    result = replay_event_chain(
        [{"type": "click", "order": 1, "name": "点击", "x": 0.25, "y": 0.4}],
        "start.png",
        device,
    )
    assert result["steps"][0]["status"] == "passed"
    assert ("tap_point", 0.25, 0.4) in device.calls


def test_coordinate_long_press_holds_without_a_control():
    device = FakeDevice()
    result = replay_event_chain(
        [{"type": "long_press", "order": 1, "name": "长按", "x": 0.5, "y": 0.5, "duration_ms": 800}],
        "start.png",
        device,
    )
    assert result["steps"][0]["status"] == "passed"
    assert ("long_press_point", 0.5, 0.5, 800) in device.calls


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


def test_recents_overview_is_closed_when_the_recording_ends_on_the_launcher():
    device = FakeDevice(match=True, nodes=[
        {"text": "打开wahda应用信息。", "bounds": {"x": 0.1, "y": 0.3, "w": 0.3, "h": 0.08}},
        {"text": "系统桌面", "bounds": {"x": 0.55, "y": 0.3, "w": 0.2, "h": 0.05}},
    ])
    device.foreground_package = lambda: "com.miui.home"

    def press_home():
        device.calls.append(("home",))
        device.nodes = [{"resource_id": "com.miui.home:id/hotseat", "bounds": {"x": 0, "y": 0.9, "w": 1, "h": 0.1}}]

    device.press_home = press_home
    result = replay_event_chain(
        [{
            "type": "swipe",
            "order": 26,
            "name": "滑动 向上",
            "from_x": 0.44,
            "from_y": 1,
            "to_x": 0.41,
            "to_y": 0.88,
            "before": [{"text": "Post"}],
            "after": [{"resource_id": "com.miui.home:id/hotseat"}],
        }],
        "start.png",
        device,
    )
    assert result["passed"] is True
    assert result["steps"][0]["reason"] == ""
    assert ("home",) in device.calls


def test_swipe_does_not_fail_because_the_next_title_starts_with_q():
    device = FakeDevice(match=True, nodes=[
        {"text": "For You", "bounds": {"x": 0.05, "y": 0.12, "w": 0.15, "h": 0.04}},
        {"text": "Following", "bounds": {"x": 0.25, "y": 0.12, "w": 0.15, "h": 0.04}},
    ])
    device.press_back = lambda: device.calls.append(("back",))
    result = replay_event_chain(
        [
            {"type": "swipe", "order": 17, "name": "滑动", "from_x": 0.46, "from_y": 0.65, "to_x": 0.66, "to_y": 0.35},
            {"type": "click", "order": 18, "name": "点击 Q", "text": "Q&#10;16h", "x": 0.22, "y": 0.51},
        ],
        "start.png",
        device,
    )
    assert [item["status"] for item in result["steps"]] == ["passed", "passed"]
    assert result["steps"][0]["reason"] == ""
    assert ("back",) not in device.calls
    assert ("tap_point", 0.22, 0.51) in device.calls


def test_wrapped_icon_name_counts_as_the_recorded_control():
    device = FakeDevice(match=True, nodes=[
        {"text": "Ask Sheikh\nWahda", "bounds": {"x": 0.7, "y": 0.28, "w": 0.15, "h": 0.08}},
        {"text": "2000人群_48\n0 Members", "bounds": {"x": 0.2, "y": 0.65, "w": 0.3, "h": 0.05}},
    ])
    device.press_back = lambda: device.calls.append(("back",))
    result = replay_event_chain(
        [
            {"type": "click", "order": 9, "name": "点击 2000人群_48", "text": "2000人群_48&#10;0 Members", "x": 0.62, "y": 0.68},
            {
                "type": "click",
                "order": 11,
                "name": "点击 Ask Sheikh Wahda",
                "text": "Ask Sheikh Wahda&#10;Your Islamic learning companion",
                "x": 0.78,
                "y": 0.32,
            },
        ],
        "start.png",
        device,
    )
    assert [item["status"] for item in result["steps"]] == ["passed", "passed"]
    assert result["steps"][0]["reason"] == ""
    assert ("back",) not in device.calls
    assert ("click", "2000人群_48\n0 Members") in device.calls
    assert ("click", "Ask Sheikh\nWahda") in device.calls


def test_top_left_finger_does_not_open_a_control_on_the_other_side():
    device = FakeDevice(match=True, nodes=[
        {"text": "Ask Sheikh\nWahda", "bounds": {"x": 0.7, "y": 0.26, "w": 0.16, "h": 0.1}},
        {"text": "Discover", "bounds": {"x": 0.05, "y": 0.08, "w": 0.2, "h": 0.04}},
    ])

    def tap_point(x, y):
        device.calls.append(("tap_point", x, y))
        if y > 0.8:
            device.nodes = [
                {"text": "For You", "bounds": {"x": 0.05, "y": 0.12, "w": 0.15, "h": 0.04}},
                {"text": "Following", "bounds": {"x": 0.25, "y": 0.12, "w": 0.15, "h": 0.04}},
                {"text": "Community", "bounds": {"x": 0.45, "y": 0.12, "w": 0.15, "h": 0.04}},
                {"text": "Livestreams", "bounds": {"x": 0.65, "y": 0.12, "w": 0.2, "h": 0.04}},
            ]

    device.tap_point = tap_point
    result = replay_event_chain(
        [
            {
                "type": "click",
                "order": 11,
                "name": "点击 Ask Sheikh Wahda",
                "text": "Ask Sheikh Wahda&#10;Your Islamic learning companion",
                "x": 0.06,
                "y": 0.09,
                "before": [{"text": "Ask Sheikh Wahda"}],
                "after": [{"text": "Ask Sheikh Wahda"}],
            },
            {
                "type": "click",
                "order": 15,
                "name": "点击 67%,92%",
                "x": 0.67,
                "y": 0.92,
                "before": [{"text": "Ask Sheikh Wahda"}],
                "after": [
                    {"text": "For You"},
                    {"text": "Following"},
                    {"text": "Community"},
                    {"text": "Livestreams"},
                ],
            },
            {"type": "swipe", "order": 17, "name": "滑动", "from_x": 0.5, "from_y": 0.6, "to_x": 0.5, "to_y": 0.3},
        ],
        "start.png",
        device,
    )
    assert [item["status"] for item in result["steps"]] == ["passed", "passed", "passed"]
    assert ("click", "Ask Sheikh\nWahda") not in device.calls
    assert ("tap_point", 0.06, 0.09) in device.calls
    assert ("tap_point", 0.67, 0.92) in device.calls


def test_back_returns_to_the_page_that_has_the_next_control():
    device = FakeDevice(
        match=True,
        nodes=[
            {"text": "Ask Sheikh Wahda", "bounds": {"x": 0.7, "y": 0.28, "w": 0.15, "h": 0.08}},
            {"text": "2000人群_48", "bounds": {"x": 0.4, "y": 0.6, "w": 0.3, "h": 0.06}},
        ],
    )

    def click(node):
        device.calls.append(("click", node.get("resource_id") or node.get("text")))
        device.nodes = [{"text": "How can Sheikh Wahda help you today?", "bounds": {"x": 0.1, "y": 0.3, "w": 0.8, "h": 0.1}}]

    def press_back():
        device.calls.append(("back",))
        device.nodes = [
            {"text": "Ask Sheikh Wahda", "bounds": {"x": 0.7, "y": 0.28, "w": 0.15, "h": 0.08}},
            {"text": "2000人群_48", "bounds": {"x": 0.4, "y": 0.6, "w": 0.3, "h": 0.06}},
        ]

    device.click = click
    device.press_back = press_back
    result = replay_event_chain(
        [
            {"type": "click", "order": 1, "name": "点击 Ask Sheikh Wahda", "text": "Ask Sheikh Wahda", "x": 0.8, "y": 0.3},
            {"type": "click", "order": 2, "name": "点击 2000人群_48", "text": "2000人群_48&#10;0 Members", "x": 0.64, "y": 0.68},
        ],
        "start.png",
        device,
    )
    assert [item["status"] for item in result["steps"]] == ["passed", "passed"]
    assert ("back",) not in device.calls
    assert ("tap_point", 0.64, 0.68) in device.calls


def test_coordinate_tap_is_skipped_when_its_result_page_is_already_showing():
    device = FakeDevice(match=True, nodes=[
        {"text": "Discover", "bounds": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.04}},
        {"text": "Ask Sheikh Wahda", "bounds": {"x": 0.7, "y": 0.28, "w": 0.15, "h": 0.08}},
    ])
    result = replay_event_chain(
        [
            {
                "type": "click",
                "order": 1,
                "name": "点击 81%,30%",
                "x": 0.81,
                "y": 0.3,
                "before": [{"resource_id": "com.miui.home:id/hotseat"}],
                "after": [{"text": "Discover"}],
            },
            {"type": "click", "order": 2, "name": "点击 Ask Sheikh Wahda", "text": "Ask Sheikh Wahda", "x": 0.8, "y": 0.3},
        ],
        "start.png",
        device,
    )
    assert result["steps"][0]["status"] == "passed"
    assert ("tap_point", 0.81, 0.3) not in device.calls
    assert ("click", "Ask Sheikh Wahda") in device.calls


def test_stale_home_dump_does_not_tap_a_launcher_point_inside_the_app():
    device = FakeDevice(match=True, nodes=[
        {"resource_id": "com.miui.home:id/hotseat", "bounds": {"x": 0, "y": 0.9, "w": 1, "h": 0.1}},
        {"text": "Discover", "bounds": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.04}},
        {"text": "Ask Sheikh Wahda", "bounds": {"x": 0.7, "y": 0.28, "w": 0.15, "h": 0.08}},
    ])
    device.foreground_package = lambda: "com.example.wahda"
    result = replay_event_chain(
        [
            {
                "type": "click",
                "order": 1,
                "name": "点击 81%,30%",
                "x": 0.81,
                "y": 0.3,
                "before": [{"resource_id": "com.miui.home:id/hotseat"}],
                "after": [{"text": "Discover"}],
            },
            {"type": "click", "order": 2, "name": "点击 Ask Sheikh Wahda", "text": "Ask Sheikh Wahda", "x": 0.8, "y": 0.3},
        ],
        "start.png",
        device,
    )
    assert result["steps"][0]["status"] == "passed"
    assert ("tap_point", 0.81, 0.3) not in device.calls
    assert ("click", "Ask Sheikh Wahda") in device.calls


def test_desktop_tap_that_opens_the_app_is_not_failed_for_a_stale_launcher_dump():
    device = FakeDevice(match=True, nodes=[
        {"resource_id": "com.miui.home:id/hotseat", "bounds": {"x": 0, "y": 0.9, "w": 1, "h": 0.1}},
    ])
    device.package = "com.miui.home"
    device.foreground_package = lambda: device.package

    def tap_point(x, y):
        device.calls.append(("tap_point", x, y))
        device.package = "com.example.wahda"
        device.nodes = [
            {"text": "Discover", "bounds": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.04}},
            {"text": "Search", "bounds": {"x": 0.1, "y": 0.2, "w": 0.2, "h": 0.04}},
            {"text": "Prayer Time", "bounds": {"x": 0.1, "y": 0.3, "w": 0.2, "h": 0.04}},
            {"text": "Al-Quran", "bounds": {"x": 0.3, "y": 0.3, "w": 0.2, "h": 0.04}},
            {"text": "Ask Sheikh Wahda", "bounds": {"x": 0.7, "y": 0.28, "w": 0.15, "h": 0.08}},
            {"text": "2000人群_48", "bounds": {"x": 0.2, "y": 0.65, "w": 0.3, "h": 0.05}},
        ]

    device.tap_point = tap_point
    result = replay_event_chain(
        [
            {
                "type": "click",
                "order": 1,
                "name": "点击 36%,12%",
                "x": 0.36,
                "y": 0.12,
                "after": [{"resource_id": "com.miui.home:id/hotseat"}],
            },
            {"type": "wait", "order": 2, "name": "等待", "duration_ms": 1000},
            {
                "type": "click",
                "order": 3,
                "name": "点击 81%,30%",
                "x": 0.81,
                "y": 0.3,
                "before": [{"resource_id": "com.miui.home:id/hotseat"}],
                "after": [
                    {"text": "Discover"},
                    {"text": "Search"},
                    {"text": "Prayer Time"},
                    {"text": "Al-Quran"},
                ],
            },
            {"type": "click", "order": 5, "name": "点击 Ask Sheikh Wahda", "text": "Ask Sheikh Wahda", "x": 0.8, "y": 0.3},
            {"type": "click", "order": 7, "name": "点击 2000人群_48", "text": "2000人群_48&#10;0 Members", "x": 0.64, "y": 0.68},
        ],
        "start.png",
        device,
        start_page={
            "package": "com.miui.home",
            "activity": "com.miui.home.launcher.Launcher",
            "anchors": [{"resource_id": "com.miui.home:id/hotseat"}],
        },
    )
    assert [item["status"] for item in result["steps"]] == ["passed", "passed", "passed", "passed", "passed"]
    assert ("tap_point", 0.81, 0.3) not in device.calls
    assert ("click", "Ask Sheikh Wahda") in device.calls
    assert ("click", "2000人群_48") in device.calls


def test_missed_desktop_point_searches_for_the_recorded_icon():
    device = FakeDevice(match=True, nodes=[
        {"resource_id": "com.miui.home:id/hotseat", "bounds": {"x": 0, "y": 0.9, "w": 1, "h": 0.1}},
    ])
    device.package = "com.miui.home"
    device.foreground_package = lambda: device.package
    device.locate_icon = lambda start_screen, x, y: None

    def seek_icon(start_screen, x, y):
        device.calls.append(("seek_icon", start_screen, x, y))
        return 0.36, 0.12

    def tap_point(x, y):
        device.calls.append(("tap_point", x, y))
        if (x, y) == (0.36, 0.12):
            device.package = "com.example.wahda"
            device.nodes = [
                {"text": "Discover", "bounds": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.04}},
                {"text": "Ask Sheikh Wahda", "bounds": {"x": 0.7, "y": 0.28, "w": 0.15, "h": 0.08}},
            ]

    device.seek_icon = seek_icon
    device.tap_point = tap_point
    result = replay_event_chain(
        [
            {
                "type": "click",
                "order": 1,
                "name": "点击 36%,12%",
                "x": 0.36,
                "y": 0.12,
                "after": [{"resource_id": "com.miui.home:id/hotseat"}],
            },
            {
                "type": "click",
                "order": 3,
                "name": "点击 81%,30%",
                "x": 0.81,
                "y": 0.3,
                "before": [{"resource_id": "com.miui.home:id/hotseat"}],
                "after": [{"text": "Discover"}],
            },
            {"type": "click", "order": 5, "name": "点击 Ask Sheikh Wahda", "text": "Ask Sheikh Wahda", "x": 0.8, "y": 0.3},
        ],
        "start.png",
        device,
    )
    assert result["steps"][0]["status"] == "passed"
    assert result["steps"][1]["status"] == "passed"
    assert ("seek_icon", "start.png", 0.36, 0.12) in device.calls
    assert ("click", "Ask Sheikh Wahda") in device.calls


def test_reaching_the_next_control_keeps_the_step_after_going_back():
    device = FakeDevice(match=True, nodes=[
        {"text": "2000人群_48", "bounds": {"x": 0.2, "y": 0.65, "w": 0.3, "h": 0.05}},
    ])
    device.package = "com.example.wahda"
    device.foreground_package = lambda: device.package

    def click(node):
        device.calls.append(("click", node.get("text")))
        device.nodes = [
            {"text": "Ask Sheikh Wahda", "bounds": {"x": 0.1, "y": 0.08, "w": 0.4, "h": 0.05}},
            {"text": "Salam, test 5", "bounds": {"x": 0.1, "y": 0.2, "w": 0.4, "h": 0.05}},
        ]

    def press_back():
        device.calls.append(("back",))
        device.nodes = [{"text": "2000人群_48", "bounds": {"x": 0.2, "y": 0.65, "w": 0.3, "h": 0.05}}]

    device.click = click
    device.press_back = press_back
    result = replay_event_chain(
        [
            {
                "type": "click",
                "order": 7,
                "name": "点击 2000人群_48",
                "text": "2000人群_48",
                "before": [{"text": "Discover"}],
                "after": [{"text": "Ask Sheikh Wahda"}, {"text": "Salam, test 5"}],
            },
            {"type": "click", "order": 9, "name": "点击 2000人群_48", "text": "2000人群_48", "x": 0.62, "y": 0.68},
        ],
        "start.png",
        device,
    )
    assert [item["status"] for item in result["steps"]] == ["passed", "passed"]
    assert result["steps"][0]["reason"] == ""
    assert ("back",) not in device.calls
    assert ("click", "2000人群_48") in device.calls
    assert ("tap_point", 0.62, 0.68) in device.calls


def test_opening_the_app_returns_to_the_recorded_page_before_the_flow():
    device = FakeDevice(match=True, nodes=[{"text": "Ask Sheikh Wahda", "bounds": {"x": 0.1, "y": 0.08, "w": 0.4, "h": 0.05}}])
    device.package = "com.miui.home"
    device.foreground_package = lambda: device.package

    def tap_point(x, y):
        device.calls.append(("tap_point", x, y))
        device.package = "com.example.wahda"

    def press_back():
        device.calls.append(("back",))
        device.nodes = [{"text": "Discover", "bounds": {"x": 0.05, "y": 0.9, "w": 0.12, "h": 0.04}}]

    device.tap_point = tap_point
    device.press_back = press_back
    result = replay_event_chain(
        [
            {"type": "click", "order": 1, "name": "点击 41%,11%", "x": 0.41, "y": 0.11},
            {"type": "wait", "order": 2, "name": "等待 1000毫秒", "duration_ms": 1000},
            {"type": "click", "order": 3, "name": "点击 Discover", "text": "Discover", "x": 0.14, "y": 0.93},
        ],
        "start.png",
        device,
    )
    assert [item["status"] for item in result["steps"]] == ["passed", "passed", "passed"]
    assert ("back",) not in device.calls
    assert ("tap_point", 0.14, 0.93) in device.calls


def test_opening_the_app_fails_when_the_recorded_page_cannot_be_found():
    device = FakeDevice(
        match=True,
        nodes=[{"text": "wahda", "bounds": {"x": 0.3, "y": 0.08, "w": 0.1, "h": 0.04}}],
    )
    device.package = "com.miui.home"
    device.foreground_package = lambda: device.package

    def click(node):
        device.calls.append(("click", node.get("resource_id") or node.get("text")))
        device.package = "com.example.wahda"
        device.nodes = [{"text": "聊天", "bounds": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.05}}]

    def press_back():
        device.calls.append(("back",))
        device.package = "com.miui.home"

    device.click = click
    device.press_back = press_back
    result = replay_event_chain(
        [
            {"type": "click", "order": 1, "name": "点击 wahda", "text": "wahda", "x": 0.4, "y": 0.11},
            {"type": "click", "order": 2, "name": "点击 Discover", "text": "Discover", "x": 0.14, "y": 0.93},
        ],
        "start.png",
        device,
    )
    assert result["passed"] is True
    assert result["steps"][0]["reason"] == ""
    assert ("back",) not in device.calls
    assert ("tap_point", 0.14, 0.93) in device.calls
    assert ("click", "Discover") not in device.calls


def test_click_passes_when_the_recorded_next_screen_comes_back():
    device = FakeDevice(
        match=True,
        nodes=[
            {"text": "Discover", "bounds": {"x": 0.05, "y": 0.9, "w": 0.12, "h": 0.04}},
            {"text": "Ask Sheikh Wahda", "bounds": {"x": 0.7, "y": 0.28, "w": 0.15, "h": 0.08}},
        ],
    )
    result = replay_event_chain(
        [
            {"type": "click", "order": 1, "name": "点击 Discover", "text": "Discover", "x": 0.14, "y": 0.93},
            {"type": "wait", "order": 2, "name": "等待 1000毫秒", "duration_ms": 1000},
            {"type": "click", "order": 3, "name": "点击 Ask Sheikh Wahda", "text": "Ask Sheikh Wahda", "x": 0.83, "y": 0.32},
        ],
        "start.png",
        device,
    )
    assert [item["status"] for item in result["steps"]] == ["passed", "passed", "passed"]
    assert ("click", "Discover") in device.calls
    assert ("click", "Ask Sheikh Wahda") in device.calls


def test_recorded_start_page_is_reached_by_going_back():
    device = FakeDevice(match=False, nodes=[{"text": "详情", "bounds": {"x": 0.1, "y": 0.2, "w": 0.2, "h": 0.05}}])
    device.package = "com.example.app"
    device.foreground_package = lambda: device.package

    def press_back():
        device.calls.append(("back",))
        device.nodes = [{"text": "首页", "resource_id": "com.app:id/tab", "bounds": {"x": 0.1, "y": 0.9, "w": 0.1, "h": 0.04}}]

    device.press_back = press_back
    result = replay_event_chain(
        [{"type": "click", "order": 1, "name": "点击 首页", "text": "首页"}],
        "start.png",
        device,
        start_page={"package": "com.example.app", "activity": ".Main", "anchors": [{"text": "首页"}, {"resource_id": "com.app:id/tab"}]},
    )
    assert result["start_screen_mismatch"] is False
    assert ("back",) in device.calls
    assert ("match", 0.08) not in device.calls
    assert result["steps"][0]["status"] == "passed"


def test_cold_start_when_back_stays_on_the_wrong_page():
    device = FakeDevice(match=False, nodes=[{"text": "详情", "bounds": {"x": 0.1, "y": 0.2, "w": 0.2, "h": 0.05}}])
    device.package = "com.example.app"
    device.foreground_package = lambda: device.package

    def press_back():
        device.calls.append(("back",))

    def restart_app(package, activity):
        device.calls.append(("restart", package, activity))
        device.nodes = [{"text": "首页", "resource_id": "com.app:id/tab", "bounds": {"x": 0.1, "y": 0.9, "w": 0.1, "h": 0.04}}]

    device.press_back = press_back
    device.restart_app = restart_app
    result = replay_event_chain(
        [{"type": "wait", "order": 1, "name": "等待", "duration_ms": 1}],
        "start.png",
        device,
        start_page={"package": "com.example.app", "activity": ".Main", "anchors": [{"text": "首页"}]},
    )
    assert result["start_screen_mismatch"] is False
    assert ("restart", "com.example.app", ".Main") in device.calls
    assert device.calls.index(("restart", "com.example.app", ".Main")) > device.calls.index(("back",))


def test_another_app_is_restarted_without_pressing_back():
    device = FakeDevice(match=False, nodes=[{"text": "桌面", "bounds": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.05}}])
    device.package = "com.miui.home"
    device.foreground_package = lambda: device.package

    def press_back():
        device.calls.append(("back",))

    def restart_app(package, activity):
        device.calls.append(("restart", package, activity))
        device.package = package
        device.nodes = [{"text": "首页", "bounds": {"x": 0.1, "y": 0.2, "w": 0.2, "h": 0.05}}]

    device.press_back = press_back
    device.restart_app = restart_app
    result = replay_event_chain(
        [],
        "start.png",
        device,
        start_page={"package": "com.example.app", "activity": ".Main", "anchors": [{"text": "首页"}]},
    )
    assert result["start_screen_mismatch"] is False
    assert ("back",) not in device.calls
    assert ("restart", "com.example.app", ".Main") in device.calls


def test_unrecoverable_start_page_does_not_record():
    device = FakeDevice(match=False, nodes=[{"text": "详情", "bounds": {"x": 0.1, "y": 0.2, "w": 0.2, "h": 0.05}}])
    device.package = "com.example.app"
    device.foreground_package = lambda: device.package
    device.press_back = lambda: device.calls.append(("back",))
    device.restart_app = lambda package, activity: device.calls.append(("restart", package, activity))
    result = replay_event_chain(
        [{"type": "click", "order": 1, "name": "点击 首页", "text": "首页"}],
        "start.png",
        device,
        start_page={"package": "com.example.app", "activity": ".Main", "anchors": [{"text": "首页"}]},
    )
    assert result["start_screen_mismatch"] is True
    assert result["passed"] is False
    assert result["steps"] == []
    assert ("start_record",) not in device.calls


def test_click_passes_when_the_next_page_anchors_appear():
    device = FakeDevice(nodes=[{"resource_id": "com.app:id/go", "text": "进入", "bounds": {"x": 0.2, "y": 0.4, "w": 0.2, "h": 0.08}}])

    def click(node):
        device.calls.append(("click", node.get("resource_id") or node.get("text")))
        device.nodes = [{"resource_id": "com.app:id/detail", "text": "详情", "bounds": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.08}}]

    device.click = click
    result = replay_event_chain(
        [{
            "type": "click",
            "order": 1,
            "name": "点击 进入",
            "text": "进入",
            "resource_id": "com.app:id/go",
            "before": [{"resource_id": "com.app:id/go"}],
            "after": [{"resource_id": "com.app:id/detail"}],
        }],
        "start.png",
        device,
    )
    assert result["steps"][0]["status"] == "passed"
    assert result["steps"][0]["reason"] == ""


def test_click_fails_when_the_page_stays_the_same():
    device = FakeDevice(nodes=[
        {"resource_id": "com.app:id/home", "text": "首页", "bounds": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.05}},
        {"resource_id": "com.app:id/go", "text": "进入", "bounds": {"x": 0.2, "y": 0.4, "w": 0.2, "h": 0.08}},
    ])
    result = replay_event_chain(
        [{
            "type": "click",
            "order": 1,
            "name": "点击 进入",
            "text": "进入",
            "before": [{"resource_id": "com.app:id/home"}],
            "after": [{"resource_id": "com.app:id/detail"}],
        }],
        "start.png",
        device,
    )
    assert result["passed"] is False
    assert result["steps"][0]["reason"] == "点了但页面没变"


def test_click_fails_when_a_different_page_opens():
    device = FakeDevice(nodes=[{"resource_id": "com.app:id/go", "text": "进入", "bounds": {"x": 0.2, "y": 0.4, "w": 0.2, "h": 0.08}}])

    def click(node):
        device.calls.append(("click", node.get("resource_id") or node.get("text")))
        device.nodes = [{"text": "设置", "resource_id": "com.app:id/settings", "bounds": {"x": 0.1, "y": 0.2, "w": 0.2, "h": 0.05}}]

    device.click = click
    result = replay_event_chain(
        [{
            "type": "click",
            "order": 1,
            "name": "点击 进入",
            "text": "进入",
            "before": [{"resource_id": "com.app:id/home"}],
            "after": [{"resource_id": "com.app:id/detail"}],
        }],
        "start.png",
        device,
    )
    assert result["steps"][0]["status"] == "failed"
    assert result["steps"][0]["reason"] == "进了别的页面: 设置"


def test_coordinate_click_needs_the_next_page():
    device = FakeDevice(nodes=[{"text": "首页", "resource_id": "com.app:id/home", "bounds": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.05}}])
    result = replay_event_chain(
        [{
            "type": "click",
            "order": 1,
            "name": "点击 40%,40%",
            "x": 0.4,
            "y": 0.4,
            "before": [{"resource_id": "com.app:id/home"}],
            "after": [{"text": "详情"}],
        }],
        "start.png",
        device,
    )
    assert result["steps"][0]["status"] == "failed"
    assert result["steps"][0]["reason"] == "点了但页面没变"
    assert ("tap_point", 0.4, 0.4) in device.calls


def test_input_fails_when_the_field_shows_different_text():
    device = FakeDevice(nodes=[{"resource_id": "com.app:id/name", "text": "别的", "bounds": {"x": 0.1, "y": 0.3, "w": 0.6, "h": 0.06}}])
    result = replay_event_chain(
        [{
            "type": "input",
            "order": 1,
            "name": "输入 姓名",
            "resource_id": "com.app:id/name",
            "input_text": "张三",
            "before": [{"resource_id": "com.app:id/name"}],
            "after": [{"resource_id": "com.app:id/name"}],
        }],
        "start.png",
        device,
    )
    assert result["steps"][0]["status"] == "failed"
    assert result["steps"][0]["reason"] == "输入内容不一致"


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

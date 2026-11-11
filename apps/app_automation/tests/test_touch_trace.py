from apps.app_automation.recording.screen_labels import ScreenCache, controls_from_dump
from apps.app_automation.recording.touch_trace import GestureTracker, parse_touch_device


PROFILE = """
add device 1: /dev/input/event0
  name:     "gpio-keys"
add device 2: /dev/input/event6
  name:     "goodix_ts.0"
    ABS (0003): 0035  : value 0, min 0, max 1000, fuzz 0, flat 0, resolution 0
                0036  : value 0, min 0, max 2000, fuzz 0, flat 0, resolution 0
"""


def test_parse_touch_device_picks_the_screen():
    device = parse_touch_device(PROFILE)
    assert device["path"] == "/dev/input/event6"
    assert device["x"] == 1000
    assert device["y"] == 2000


def test_vertical_gesture_becomes_a_swipe():
    tracker = GestureTracker(parse_touch_device(PROFILE), minimum=0.03)
    lines = [
        "[    10.0] /dev/input/event6: EV_ABS       ABS_MT_TRACKING_ID   0000000a",
        "[    10.0] /dev/input/event6: EV_ABS       ABS_MT_POSITION_X    000001f4",
        "[    10.0] /dev/input/event6: EV_ABS       ABS_MT_POSITION_Y    00000190",
        "[    10.0] /dev/input/event6: EV_SYN       SYN_REPORT           00000000",
        "[    10.2] /dev/input/event6: EV_ABS       ABS_MT_POSITION_Y    000005dc",
        "[    10.2] /dev/input/event6: EV_SYN       SYN_REPORT           00000000",
        "[    10.3] /dev/input/event6: EV_ABS       ABS_MT_TRACKING_ID   ffffffff",
    ]
    swipes = [swipe for swipe in (tracker.feed(line) for line in lines) if swipe]
    assert len(swipes) == 1
    assert swipes[0]["from_x"] == 0.5
    assert swipes[0]["from_y"] == 0.2
    assert swipes[0]["to_x"] == 0.5
    assert swipes[0]["to_y"] == 0.75


DUMP = """
<hierarchy>
  <node bounds="[0,0][1000,2000]" text="" content-desc="" class="android.widget.FrameLayout" />
  <node bounds="[200,200][400,400]" text="wahda" content-desc="" class="android.widget.TextView" />
</hierarchy>
"""


def test_dump_control_can_name_a_later_tap():
    cache = ScreenCache("device", reader=lambda device_id: "")
    cache.remember(controls_from_dump(DUMP), finished_at=10)
    assert cache.lookup(0.3, 0.15, now=10.1) is None
    cache.remember(
        [{"text": "下一页", "bounds": {"x": 0.2, "y": 0.1, "w": 0.2, "h": 0.1}}],
        finished_at=20,
    )
    assert cache.lookup(0.3, 0.15, now=20.1)["text"] == "wahda"


def test_icon_caption_below_the_tap_is_used():
    cache = ScreenCache("device", reader=lambda device_id: "")
    cache.remember(
        [
            {"text": "", "bounds": {"x": 0.2, "y": 0.08, "w": 0.16, "h": 0.08}},
            {"text": "wahda", "bounds": {"x": 0.2, "y": 0.17, "w": 0.16, "h": 0.03}},
        ],
        finished_at=10,
    )
    assert cache.lookup(0.28, 0.12, now=20)["text"] == "wahda"


def test_short_tap_becomes_a_click():
    tracker = GestureTracker(parse_touch_device(PROFILE), minimum=0.03)
    lines = [
        "[    10.0] /dev/input/event6: EV_ABS       ABS_MT_TRACKING_ID   00000001",
        "[    10.0] /dev/input/event6: EV_ABS       ABS_MT_POSITION_X    000001f4",
        "[    10.0] /dev/input/event6: EV_ABS       ABS_MT_POSITION_Y    00000190",
        "[    10.0] /dev/input/event6: EV_SYN       SYN_REPORT           00000000",
        "[    10.1] /dev/input/event6: EV_ABS       ABS_MT_TRACKING_ID   ffffffff",
    ]
    gestures = [item for item in (tracker.feed(line) for line in lines) if item]
    assert len(gestures) == 1
    assert gestures[0]["event_type"] == "click"
    assert gestures[0]["x"] == 0.5
    assert gestures[0]["y"] == 0.2
    assert gestures[0]["duration_ms"] == 100


def test_held_tap_becomes_a_long_press():
    tracker = GestureTracker(parse_touch_device(PROFILE), minimum=0.03, long_press_ms=500)
    lines = [
        "[    10.0] /dev/input/event6: EV_ABS       ABS_MT_TRACKING_ID   00000001",
        "[    10.0] /dev/input/event6: EV_ABS       ABS_MT_POSITION_X    000001f4",
        "[    10.0] /dev/input/event6: EV_ABS       ABS_MT_POSITION_Y    00000190",
        "[    10.0] /dev/input/event6: EV_SYN       SYN_REPORT           00000000",
        "[    10.8] /dev/input/event6: EV_ABS       ABS_MT_TRACKING_ID   ffffffff",
    ]
    gestures = [item for item in (tracker.feed(line) for line in lines) if item]
    assert gestures[0]["event_type"] == "long_press"
    assert gestures[0]["duration_ms"] == 800

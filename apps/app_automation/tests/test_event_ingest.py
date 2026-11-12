import pytest
from apps.app_automation.recording.ingest import parse_ingested_event


def test_click_event_keeps_identity_and_template():
    step = parse_ingested_event({
        "event_type": "click",
        "resource_id": "com.app:id/login",
        "content_desc": "",
        "text": "登录",
        "class_name": "Button",
        "bounds": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.1},
        "screen": {"width": 1080, "height": 2400},
        "duration_ms": 80,
    }, order=1, template="t.png")
    assert step["type"] == "click"
    assert step["platform"] == "android"
    assert step["accessibility_id"] == ""
    assert step["template"] == "t.png"
    assert step["order"] == 1
    assert step["name"] == "点击 登录"


def test_password_input_drops_text():
    step = parse_ingested_event({
        "event_type": "input",
        "text": "secret",
        "password": True,
        "resource_id": "com.app:id/pwd",
        "class_name": "EditText",
        "bounds": {"x": 0, "y": 0, "w": 1, "h": 0.05},
        "screen": {"width": 1080, "height": 1920},
    }, order=2, template="pwd.png")
    assert step["input_text"] == ""
    assert step["password"] is True


def test_swipe_distance_is_clamped():
    step = parse_ingested_event({
        "event_type": "swipe",
        "direction": "up",
        "distance": 2.4,
        "resource_id": "com.app:id/list",
        "bounds": {"x": 0, "y": 0.2, "w": 1, "h": 0.6},
        "screen": {"width": 1080, "height": 1920},
    }, order=3, template="list.png")
    assert step["distance"] == 1
    assert step["direction"] == "up"


def test_finger_swipe_keeps_endpoints():
    step = parse_ingested_event({
        "event_type": "swipe",
        "from_x": 0.2,
        "from_y": 0.8,
        "to_x": 0.2,
        "to_y": 0.3,
    }, order=4, template="")
    assert step["from_x"] == 0.2
    assert step["to_y"] == 0.3
    assert step["direction"] == "up"
    assert step["name"] == "滑动 向上 从 20%,80% 到 20%,30%"


def test_control_label_replaces_the_coordinate_name():
    step = parse_ingested_event({
        "event_type": "click",
        "x": 0.3,
        "y": 0.15,
        "control_label": "wahda",
    }, order=1, template="")
    assert step["name"] == "点击 wahda"
    assert step["x"] == 0.3
    assert step["text"] == "wahda"


def test_smallest_labeled_control_at_the_point_is_used():
    from apps.app_automation.recording.ingest import control_at_point

    nodes = [
        {"text": "Prayer Times", "bounds": {"x": 0, "y": 0, "w": 1, "h": 1}},
        {"text": "Customize Theme", "bounds": {"x": 0.1, "y": 0.8, "w": 0.8, "h": 0.1}},
        {"text": "", "content_desc": "", "bounds": {"x": 0.7, "y": 0.4, "w": 0.1, "h": 0.08}},
    ]
    found = control_at_point(nodes, 0.5, 0.85)
    assert found["text"] == "Customize Theme"
    assert control_at_point(nodes, 0.75, 0.44)["text"] == "Prayer Times"


def test_reported_control_renames_the_touch_click():
    from apps.app_automation.recording.ingest import apply_control_label

    click = {"type": "click", "order": 1, "name": "点击 30%,15%", "x": 0.3, "y": 0.15}
    renamed = apply_control_label(
        [click],
        "click",
        "wahda",
        {"x": 0.2, "y": 0.1, "w": 0.2, "h": 0.1},
    )
    assert renamed["name"] == "点击 wahda"
    assert apply_control_label([click], "click", "返回", {"x": 0, "y": 0, "w": 0.1, "h": 0.1}) is None


def test_touch_click_uses_the_point_in_its_name():
    step = parse_ingested_event({
        "event_type": "click",
        "x": 0.56,
        "y": 0.2,
        "duration_ms": 80,
    }, order=1, template="")
    assert step["name"] == "点击 56%,20%"
    assert step["x"] == 0.56
    assert step["y"] == 0.2


def test_text_change_drops_key_taps_and_keeps_the_field_tap():
    from apps.app_automation.recording.ingest import absorb_typing_clicks

    field = {"type": "click", "order": 1, "x": 0.5, "y": 0.3}
    key = {"type": "click", "order": 2, "x": 0.2, "y": 0.9}
    kept = absorb_typing_clicks([field, key])
    assert [step["order"] for step in kept] == [1]
    assert kept[0]["y"] == 0.3
    typed = absorb_typing_clicks(kept + [{"type": "input", "order": 2, "input_text": "你"}, key])
    assert [step["type"] for step in typed] == ["click", "input"]


def test_later_field_text_replaces_the_same_input():
    from apps.app_automation.recording.ingest import parse_ingested_event, place_input

    bounds = {"x": 0.04, "y": 0.54, "w": 0.91, "h": 0.06}
    first = parse_ingested_event({
        "event_type": "input", "text": "你好", "input_text": "你好",
        "class_name": "android.widget.EditText", "bounds": bounds,
    }, order=1, template="")
    key = {"type": "click", "order": 2, "x": 0.9, "y": 0.84}
    second = parse_ingested_event({
        "event_type": "input", "text": "您好", "input_text": "您好",
        "class_name": "android.widget.EditText", "bounds": bounds,
    }, order=3, template="")
    steps, stored = place_input([first, key], second)
    assert stored["input_text"] == "您好"
    assert [step["type"] for step in steps] == ["input"]
    assert steps[0]["input_text"] == "您好"


def test_empty_clear_keeps_the_typed_text():
    from apps.app_automation.recording.ingest import parse_ingested_event, place_input

    bounds = {"x": 0.04, "y": 0.54, "w": 0.91, "h": 0.06}
    typed = parse_ingested_event({
        "event_type": "input", "text": "您好", "input_text": "您好",
        "class_name": "android.widget.EditText", "bounds": bounds,
    }, order=1, template="")
    cleared = parse_ingested_event({
        "event_type": "input", "text": "", "input_text": "",
        "class_name": "android.widget.EditText", "bounds": bounds,
    }, order=2, template="")
    steps, stored = place_input([typed], cleared)
    assert stored is None
    assert steps[0]["input_text"] == "您好"


def test_unknown_event_rejected():
    with pytest.raises(ValueError):
        parse_ingested_event({"event_type": "rotate"}, order=1, template="")

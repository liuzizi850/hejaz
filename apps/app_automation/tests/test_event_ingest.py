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


def test_unknown_event_rejected():
    with pytest.raises(ValueError):
        parse_ingested_event({"event_type": "rotate"}, order=1, template="")

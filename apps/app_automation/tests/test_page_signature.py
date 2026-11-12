from apps.app_automation.recording.foreground import activity_from_focus
from apps.app_automation.recording.page_signature import (
    component_name,
    event_chain_document,
    has_start_page,
    merge_screen,
    page_matches,
    remember_after,
    remember_before,
    stable_anchors,
)


FOCUS = "mCurrentFocus=Window{abc u0 com.example.app/.MainActivity}"


def test_activity_comes_from_the_focused_window():
    assert activity_from_focus(FOCUS) == ".MainActivity"
    assert activity_from_focus("no focus") == ""


def test_stable_anchors_skip_clock_badge_and_full_screen():
    anchors = stable_anchors([
        {"resource_id": "android:id/content", "text": "", "bounds": {"x": 0, "y": 0, "w": 1, "h": 1}},
        {"resource_id": "com.app:id/badge", "text": "3", "bounds": {"x": 0.8, "y": 0.1, "w": 0.04, "h": 0.03}},
        {"resource_id": "", "text": "12:30", "bounds": {"x": 0.4, "y": 0.01, "w": 0.1, "h": 0.03}},
        {"resource_id": "com.app:id/title", "text": "首页", "bounds": {"x": 0.3, "y": 0.1, "w": 0.2, "h": 0.05}},
        {"resource_id": "", "text": "发现", "bounds": {"x": 0.1, "y": 0.8, "w": 0.1, "h": 0.04}},
        {"resource_id": "com.app:id/tab_home", "text": "", "bounds": {"x": 0.05, "y": 0.9, "w": 0.15, "h": 0.05}},
    ])
    assert anchors == [
        {"resource_id": "com.app:id/title"},
        {"resource_id": "com.app:id/tab_home"},
        {"text": "发现"},
    ]


def test_page_matches_only_when_package_and_every_anchor_are_present():
    expected = {"package": "com.example.app", "anchors": [{"text": "首页"}, {"resource_id": "com.app:id/tab"}]}
    nodes = [{"text": "首页", "resource_id": "com.app:id/tab"}]
    assert page_matches(expected, "com.example.app", nodes) is True
    assert page_matches(expected, "com.other", nodes) is False
    assert page_matches(expected, "com.example.app", [{"text": "首页"}]) is False
    assert has_start_page({"package": "com.example.app"}) is False
    assert has_start_page(expected) is True


def test_remember_before_and_after_uses_the_screen_between_actions():
    previous = {"type": "click", "order": 1}
    remember_before(previous, [{"resource_id": "com.app:id/home", "text": "首页", "bounds": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.05}}])
    current = {"type": "click", "order": 2}
    steps = [previous]
    assert remember_after(steps, [{"resource_id": "com.app:id/detail", "text": "详情", "bounds": {"x": 0.1, "y": 0.2, "w": 0.2, "h": 0.05}}]) is previous
    remember_before(current, [{"resource_id": "com.app:id/detail", "text": "详情", "bounds": {"x": 0.1, "y": 0.2, "w": 0.2, "h": 0.05}}])
    assert previous["before"] == [{"resource_id": "com.app:id/home"}]
    assert previous["after"] == [{"resource_id": "com.app:id/detail"}]
    assert current["before"] == [{"resource_id": "com.app:id/detail"}]
    assert remember_after(steps, [{"text": "别的页", "bounds": {"x": 0.1, "y": 0.2, "w": 0.2, "h": 0.05}}]) is None


def test_component_name_and_saved_chain_keep_the_start_page():
    assert component_name("com.example.app", ".MainActivity") == "com.example.app/com.example.app.MainActivity"
    screen = merge_screen({"start_page": {"package": "com.example.app", "anchors": [{"text": "首页"}]}}, {"width": 1080, "height": 1920})
    document = event_chain_document(screen, [{"type": "click"}])
    assert document["start_page"]["package"] == "com.example.app"
    assert document["screen"] == {"width": 1080, "height": 1920}
    assert "start_page" not in document["screen"]

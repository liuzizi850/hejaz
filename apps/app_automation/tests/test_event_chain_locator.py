from apps.app_automation.recording.locator import select_by_identity


def test_resource_id_wins_over_text():
    step = {"resource_id": "com.app:id/login", "text": "登录", "class_name": "Button", "bounds": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.1}}
    nodes = [
        {"resource_id": "com.app:id/other", "text": "登录", "class_name": "Button", "bounds": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.1}},
        {"resource_id": "com.app:id/login", "text": "别的", "class_name": "Text", "bounds": {"x": 0.5, "y": 0.5, "w": 0.2, "h": 0.1}},
    ]
    assert select_by_identity(step, nodes)["resource_id"] == "com.app:id/login"


def test_content_desc_when_no_resource_id():
    step = {"resource_id": "", "content_desc": "关闭", "text": "", "class_name": "", "bounds": {"x": 0, "y": 0, "w": 0.1, "h": 0.1}}
    nodes = [{"resource_id": "", "content_desc": "关闭", "text": "", "class_name": "Image", "bounds": {"x": 0, "y": 0, "w": 0.1, "h": 0.1}}]
    assert select_by_identity(step, nodes)["content_desc"] == "关闭"


def test_text_and_class_name():
    step = {"text": "确定", "class_name": "Button", "bounds": {"x": 0.4, "y": 0.8, "w": 0.2, "h": 0.1}}
    nodes = [{"text": "确定", "class_name": "Text", "bounds": {"x": 0.4, "y": 0.8, "w": 0.2, "h": 0.1}}]
    assert select_by_identity(step, nodes) is None
    nodes.append({"text": "确定", "class_name": "Button", "bounds": {"x": 0.4, "y": 0.8, "w": 0.2, "h": 0.1}})
    assert select_by_identity(step, nodes)["class_name"] == "Button"


def test_multiple_matches_pick_closest_bounds():
    step = {"resource_id": "com.app:id/item", "bounds": {"x": 0.0, "y": 0.0, "w": 0.2, "h": 0.1}}
    nodes = [
        {"resource_id": "com.app:id/item", "bounds": {"x": 0.7, "y": 0.7, "w": 0.2, "h": 0.1}},
        {"resource_id": "com.app:id/item", "bounds": {"x": 0.05, "y": 0.02, "w": 0.2, "h": 0.1}},
    ]
    chosen = select_by_identity(step, nodes)
    assert chosen["bounds"]["x"] == 0.05


def test_no_identity_returns_none():
    assert select_by_identity({"bounds": {"x": 0, "y": 0, "w": 1, "h": 1}}, []) is None

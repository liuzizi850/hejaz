import json
from io import BytesIO

from openpyxl import load_workbook

from apps.code_monitor.excel_export import write_api_workbook
from apps.code_monitor.extract import ApiRow
from apps.code_monitor.sample_data import render_request_sample


def test_body_only_is_copyable_json():
    raw = json.dumps({
        "query": {},
        "body": {"username": "string", "age": "number", "enabled": "boolean"},
        "headers": {},
    }, ensure_ascii=False)
    assert json.loads(render_request_sample(raw)) == {
        "username": "测试用户",
        "age": 1,
        "enabled": True,
    }


def test_query_only_is_query_string():
    raw = json.dumps({
        "query": {"page": "number", "pageSize": "int", "keyword": "string"},
        "body": {},
        "headers": {},
    })
    assert render_request_sample(raw) == "page=1&pageSize=10&keyword=test"


def test_multi_layer_is_labeled_for_copy():
    raw = json.dumps({
        "query": {"id": "string"},
        "body": {"phone": "手机号"},
        "headers": {"Content-Type": "application/json", "Authorization": "string"},
    }, ensure_ascii=False)
    text = render_request_sample(raw)
    assert text.startswith("query: id=1")
    assert '"phone": "13800138000"' in text
    assert '"Content-Type": "application/json"' in text
    assert '"Authorization": "Bearer test-token"' in text


def test_nested_object_and_array_item():
    raw = json.dumps({
        "body": {
            "profile": {"email": "邮箱", "tags": "string[]"},
            "items": [{"skuId": "number", "title": "string"}],
            "roles": ["管理员", "用户"],
        }
    }, ensure_ascii=False)
    data = json.loads(render_request_sample(raw))
    assert data["profile"]["email"] == "test@example.com"
    assert data["profile"]["tags"] == ["test"]
    assert data["items"] == [{"skuId": 1, "title": "测试标题"}]
    assert data["roles"] == ["管理员", "用户"]


def test_nullable_type_still_generates_a_value():
    raw = json.dumps({"body": {"count": "int|null", "nickname": "string | null"}})
    data = json.loads(render_request_sample(raw))
    assert data == {"count": 1, "nickname": "测试用户"}


def test_enum_and_literal_values_are_kept():
    raw = json.dumps({
        "body": {"status": "enable|disable", "format": "application/json"},
    })
    data = json.loads(render_request_sample(raw))
    assert data["status"] == "enable"
    assert data["format"] == "application/json"


def test_empty_params_produce_no_sample():
    assert render_request_sample("") == ""
    assert render_request_sample("page") == ""
    assert render_request_sample('{"query": {}, "body": {}, "headers": {}}') == ""


def test_workbook_sample_column_can_be_pasted():
    params = json.dumps({
        "query": {},
        "body": {"email": "string", "password": "密码"},
        "headers": {},
    }, ensure_ascii=False)
    content = write_api_workbook([
        ApiRow("创建", "POST", "/api/users", params, "", "a.js"),
    ])
    sheet = load_workbook(BytesIO(content)).active
    assert sheet["E1"].value == "测试数据"
    assert json.loads(sheet["E2"].value) == {
        "email": "test@example.com",
        "password": "Test123456",
    }
    assert sheet["E2"].alignment.wrap_text is True

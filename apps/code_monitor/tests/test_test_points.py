import json

from apps.code_monitor.test_points import render_test_points


def _body(**fields) -> str:
    return json.dumps({"query": {}, "body": fields, "headers": {}}, ensure_ascii=False)


def test_required_string_lists_type_required_and_length():
    text = render_test_points(_body(event_name="string, required, maxLength=2000"))
    assert text == "\n".join([
        "body.event_name（string）",
        "必填：是",
        "长度：2000",
        "参数类型：string(字符串)",
        "枚举值：否",
    ])


def test_optional_enum_lists_values():
    text = render_test_points(_body(gender="string, optional, 女|男"))
    assert text == "\n".join([
        "body.gender（string）",
        "必填：否",
        "长度：-",
        "参数类型：string(字符串)",
        "枚举值：是【女、男】",
    ])


def test_number_bool_and_array_use_type_names():
    text = render_test_points(_body(
        amount="number, min=0, max=100",
        enabled="boolean",
        items="array",
    ))
    assert "body.amount（number）" in text
    assert "长度：-" in text
    assert "参数类型：number(数字)" in text
    assert "参数类型：boolean(布尔)" in text
    assert "参数类型：array(数组)" in text
    assert "枚举值：否" in text


def test_constraints_are_not_copied_into_enum_values():
    text = render_test_points(_body(gender="string, required, maxLength=20, 女|男"))
    assert "必填：是" in text
    assert "长度：20" in text
    assert "枚举值：是【女、男】" in text

    labeled = render_test_points(_body(gender="string, 必填, 女|男"))
    assert "必填：是" in labeled
    assert "枚举值：是【女、男】" in labeled

    mixed = render_test_points(_body(code="string, A|B|女|男"))
    assert "枚举值：是【A、B、女、男】" in mixed


def test_ascii_enum_and_max_length():
    text = render_test_points(_body(
        level="string, optional, low|medium|high",
        serialNo="string, maxLength=32",
    ))
    assert "枚举值：是【low、medium、high】" in text
    assert "body.serialNo（string）" in text
    assert "长度：32" in text


def test_array_keeps_item_type_required_and_length():
    text = render_test_points(_body(tags="array<string>, required, maxLength=10"))
    assert text == "\n".join([
        "body.tags（array）",
        "必填：是",
        "长度：10",
        "参数类型：array(字符串数组)",
        "枚举值：否",
    ])
    brackets = render_test_points(_body(tags="string[]"))
    assert "body.tags（array）" in brackets
    assert "参数类型：array(字符串数组)" in brackets


def test_chinese_value_list_is_an_enum():
    raw = json.dumps({"body": {"gender": ["女", "男"]}}, ensure_ascii=False)
    text = render_test_points(raw)
    assert "body.gender（string）" in text
    assert "枚举值：是【女、男】" in text
    assert "参数类型：array(数组)" not in text


def test_enum_value_optional_does_not_clear_required():
    text = render_test_points(_body(flag="string, required, yes|optional"))
    assert "必填：是" in text
    assert "枚举值：是【yes、optional】" in text


def test_nested_overflow_is_counted():
    body = {f"group{index}": {"name": "string"} for index in range(45)}
    text = render_test_points(json.dumps({"body": body}, ensure_ascii=False))
    assert text.count("（string）") == 40
    assert "其余 5 个字段同样列出必填、长度、类型和枚举" in text


def test_unknown_required_is_no_and_skips_headers():
    raw = json.dumps({
        "query": {},
        "body": {"keyword": "string", "items": [{"skuId": "number"}]},
        "headers": {"Content-Type": "application/json"},
    }, ensure_ascii=False)
    text = render_test_points(raw)
    assert "body.keyword（string）" in text
    assert "必填：否" in text
    assert "body.items[].skuId（number）" in text
    assert "参数类型：number(数字)" in text
    assert "Content-Type" not in text
    assert render_test_points("") == ""
    assert render_test_points('{"query": {}, "body": {}, "headers": {}}') == ""

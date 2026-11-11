import json

from apps.code_monitor.test_points import render_test_points


def _body(**fields) -> str:
    return json.dumps({"query": {}, "body": fields, "headers": {}}, ensure_ascii=False)


def test_required_phone_marks_empty_type_unique_and_length():
    text = render_test_points(_body(phone="string, required, unique"))
    assert "body.phone（string，必填，唯一）" in text
    assert "必填参数：不传、传空字符串、null" in text
    assert "参数类型：字符串传数字 1" in text
    assert "业务唯一性：唯一键重复提交（用已存在的手机号再提交一次）" in text
    assert "边界值：超长字符串" in text
    assert "参数可选字段" not in text


def test_optional_enum_marks_valid_and_invalid_values():
    text = render_test_points(_body(level="string, optional, low|medium|high"))
    assert "body.level（string，可选，枚举 low|medium|high）" in text
    assert "参数可选字段：不传、传 null、传有效值 low" in text
    assert "参数枚举值：合法枚举 low、medium、high；不在枚举里的值 NOT_A_VALUE" in text
    assert "必填参数" not in text


def test_number_bounds_and_bool_array_types():
    text = render_test_points(_body(
        amount="number, min=0, max=100",
        enabled="boolean",
        items="array",
    ))
    assert "边界值：最小值 0、最大值 100、刚好临界 0 和 100、超出上限 101、低于下限 -1" in text
    assert "参数类型：布尔传 0、传 1" in text
    assert "参数类型：数组传对象 {}" in text
    assert 'body.amount' in text and '参数类型：数字传字符串 "1"' in text


def test_refund_status_marks_reverse_transition():
    text = render_test_points(_body(orderStatus="string, required, 待支付|已支付|已退款"))
    assert "参数枚举值：合法枚举 待支付、已支付、已退款" in text
    assert "状态机校验：只能按业务状态流转，禁止逆状态变更（已退款订单不要再发起支付）" in text


def test_order_and_serial_numbers_are_unique_keys():
    text = render_test_points(_body(orderNo="string", serialNo="string, maxLength=32"))
    assert "用已存在的订单号再提交一次" in text
    assert "用已存在的流水号再提交一次" in text
    assert "长度刚好 32、超出 33" in text


def test_unknown_required_lists_both_cases_and_skips_headers():
    raw = json.dumps({
        "query": {},
        "body": {"keyword": "string", "items": [{"skuId": "number"}]},
        "headers": {"Content-Type": "application/json"},
    }, ensure_ascii=False)
    text = render_test_points(raw)
    assert "必填参数：不传、传空字符串、null" in text
    assert "参数可选字段：不传、传 null、传有效值 test" in text
    assert "body.items[].skuId" in text
    assert "Content-Type" not in text
    assert render_test_points("") == ""
    assert render_test_points('{"query": {}, "body": {}, "headers": {}}') == ""

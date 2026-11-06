import json

import pytest

from apps.code_monitor.batching import FileChunk
from apps.code_monitor.extract import (
    EXCEL_HEADERS,
    ModelCallError,
    call_model_with_retry,
    dedupe_rows,
    parse_api_rows,
)


def test_headers_match_spec():
    assert EXCEL_HEADERS == ["名称", "请求方式", "请求地址", "入参", "出参", "源文件"]


def test_drops_rows_missing_method_or_url():
    raw = json.dumps([
        {"name": "ok", "method": "get", "url": "/api/a", "request_params": "", "response_params": "", "source_file": "a.js"},
        {"name": "no-method", "method": "", "url": "/api/b", "source_file": "b.js"},
        {"name": "no-url", "method": "POST", "url": "  ", "source_file": "c.js"},
        {"name": "bad-method", "method": "TRACE", "url": "/api/c"},
    ])
    rows = parse_api_rows(raw)
    assert len(rows) == 1
    assert rows[0].method == "GET"
    assert rows[0].url == "/api/a"
    assert rows[0].name == "ok"


def test_rejects_non_array():
    with pytest.raises(ValueError):
        parse_api_rows('{"method": "GET"}')
    with pytest.raises(ValueError):
        parse_api_rows("not-json")


def test_coerces_object_params_and_fills_empty_name():
    raw = json.dumps([{
        "name": "",
        "method": "POST",
        "url": "/api/users",
        "request_params": {"id": 1},
        "response_params": ["name"],
        "source_file": "users.py",
    }])
    row = parse_api_rows(raw)[0]
    assert row.name == "/api/users"
    assert row.request_params == '{"id": 1}'
    assert row.response_params == '["name"]'


def test_dedupe_keeps_first_non_empty_params_and_joins_files():
    rows = parse_api_rows(json.dumps([
        {"method": "GET", "url": "/api/a", "request_params": "", "response_params": "id", "source_file": "a.js"},
        {"method": "get", "url": "/api/a", "request_params": "page", "response_params": "other", "source_file": "views.py"},
        {"method": "POST", "url": "/api/a", "request_params": "body", "response_params": "", "source_file": "b.js"},
    ]))
    merged = dedupe_rows(rows)
    assert len(merged) == 2
    assert merged[0].request_params == "page"
    assert merged[0].response_params == "id"
    assert merged[0].source_file == "a.js,views.py"
    assert merged[1].method == "POST"


def test_retry_once_then_raise(monkeypatch):
    calls = {"n": 0}

    def fake_call(config, chunks):
        calls["n"] += 1
        return "not-json"

    monkeypatch.setattr("apps.code_monitor.extract.call_model", fake_call)
    with pytest.raises(ModelCallError):
        call_model_with_retry(object(), [FileChunk("a.js", "axios.get('/a')")])
    assert calls["n"] == 2

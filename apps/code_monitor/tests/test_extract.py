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
    assert EXCEL_HEADERS == ["名称", "请求方式", "请求地址", "入参", "测试数据", "测试要点", "出参", "源文件"]


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


def test_accepts_trailing_comma_and_ignores_think_block():
    rows = parse_api_rows('[{"method": "GET", "url": "/health",},]')
    assert rows[0].url == "/health"
    thought = parse_api_rows(
        '<think>maybe [1, 2]</think>\n[{"method": "GET", "url": "/health"}]'
    )
    assert thought[0].url == "/health"


def test_accepts_array_inside_markdown_or_prose():
    rows = parse_api_rows(
        "```json\n"
        '[{"name": "上传", "method": "POST", "url": "/api/v1/files/upload", "source_file": "a.py"}]\n'
        "```\n以上是结果"
    )
    assert len(rows) == 1
    assert rows[0].method == "POST"
    assert rows[0].url == "/api/v1/files/upload"
    prose = parse_api_rows('提取结果：\n[{"method": "GET", "url": "/health"}]\n完毕')
    assert prose[0].url == "/health"


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


def test_single_file_batch_overwrites_source_file(monkeypatch):
    def fake_call(config, chunks):
        return '[{"method": "GET", "url": "/health", "source_file": "wrong.py"}]'

    monkeypatch.setattr("apps.code_monitor.extract.call_model", fake_call)
    rows = call_model_with_retry(object(), [FileChunk("src/api/health.ts", "axios.get('/health')")])
    assert rows[0].source_file == "src/api/health.ts"


def test_truncated_json_splits_one_large_chunk(monkeypatch):
    calls = {"n": 0}

    def fake_call(config, chunks):
        calls["n"] += 1
        if len(chunks[0].text) > 800:
            return '[{"method": "GET", "url": "/big"'
        return '[{"method": "GET", "url": "/ok"}]'

    monkeypatch.setattr("apps.code_monitor.extract.call_model", fake_call)
    rows = call_model_with_retry(object(), [FileChunk("a.js", "axios.get('/x')\n" * 80)])
    assert rows
    assert {row.url for row in rows} == {"/ok"}
    assert calls["n"] == 3


def test_length_finish_reason_splits_batch(monkeypatch):
    calls = {"n": 0}

    async def fake_api(config, messages, max_tokens=None):
        calls["n"] += 1
        user = messages[-1]["content"]
        if "LEFT" in user and "RIGHT" in user:
            return {
                "choices": [{
                    "finish_reason": "length",
                    "message": {"content": '[{"method": "GET", "url": "/a"'},
                }]
            }
        url = "/left" if "LEFT" in user else "/right"
        return {
            "choices": [{
                "finish_reason": "stop",
                "message": {"content": json.dumps([{"method": "GET", "url": url}])},
            }]
        }

    monkeypatch.setattr(
        "apps.requirement_analysis.models.AIModelService.call_openai_compatible_api",
        fake_api,
    )
    rows = call_model_with_retry(object(), [
        FileChunk("a.js", "LEFT"),
        FileChunk("b.js", "RIGHT"),
    ])
    assert [row.url for row in rows] == ["/left", "/right"]
    assert calls["n"] == 3


def test_truncated_json_splits_batch_instead_of_retrying_same_input(monkeypatch):
    calls = []

    def fake_call(config, chunks):
        calls.append(tuple(chunk.source_file for chunk in chunks))
        if len(chunks) > 1:
            return '[{"method": "GET", "url": "/a", "name": "unfin'
        url = "/left" if "left" in chunks[0].text else "/right"
        return json.dumps([{"method": "GET", "url": url}])

    monkeypatch.setattr("apps.code_monitor.extract.call_model", fake_call)
    rows = call_model_with_retry(object(), [
        FileChunk("a.js", "left axios.get('/left')"),
        FileChunk("b.js", "right axios.get('/right')"),
    ])
    assert [row.url for row in rows] == ["/left", "/right"]
    assert calls == [("a.js", "b.js"), ("a.js",), ("b.js",)]


def test_retry_once_then_raise(monkeypatch):
    calls = {"n": 0}

    def fake_call(config, chunks):
        calls["n"] += 1
        return "not-json"

    monkeypatch.setattr("apps.code_monitor.extract.call_model", fake_call)
    with pytest.raises(ModelCallError):
        call_model_with_retry(object(), [FileChunk("a.js", "axios.get('/a')")])
    assert calls["n"] == 2


def test_each_model_attempt_stops_at_timeout(monkeypatch):
    import asyncio

    calls = {"n": 0}

    async def hang(config, messages, max_tokens=None):
        calls["n"] += 1
        await asyncio.sleep(30)
        return {"choices": [{"message": {"content": "[]"}}]}

    monkeypatch.setattr(
        "apps.requirement_analysis.models.AIModelService.call_openai_compatible_api",
        hang,
    )
    monkeypatch.setattr("apps.code_monitor.extract.MODEL_CALL_TIMEOUT_SECONDS", 0.05)
    with pytest.raises(ModelCallError, match="模型调用超时"):
        call_model_with_retry(object(), [FileChunk("a.js", "axios.get('/a')")])
    assert calls["n"] == 2

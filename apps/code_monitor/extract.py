import asyncio
import json
from dataclasses import dataclass

from apps.code_monitor.batching import FileChunk, render_batch

MODEL_CALL_TIMEOUT_SECONDS = 120

EXCEL_HEADERS = ["名称", "请求方式", "请求地址", "入参", "出参", "源文件"]
ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}

SYSTEM_PROMPT = """你是接口提取器。下面每段代码以「文件: <路径>」开头。只根据这些代码提取 HTTP 接口。
只输出一个 JSON 数组，不要 Markdown，不要解释。
数组元素字段：
- name: 字符串。看不出名称时用请求地址
- method: GET、POST、PUT、PATCH、DELETE、HEAD、OPTIONS 之一
- url: 请求地址
- request_params: 入参。看不出来用空字符串
- response_params: 出参。看不出来用空字符串
- source_file: 原样复制该接口所在片段的文件路径
不要编造代码里没有的接口或字段。没有接口时输出 []。"""


class ModelCallError(Exception):
    pass


@dataclass
class ApiRow:
    name: str
    method: str
    url: str
    request_params: str
    response_params: str
    source_file: str


def parse_api_rows(raw: str) -> list[ApiRow]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("模型返回的内容不是合法 JSON 数组") from exc
    if not isinstance(payload, list):
        raise ValueError("模型返回的内容不是合法 JSON 数组")
    rows = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        method = str(item.get("method") or "").strip().upper()
        url = str(item.get("url") or "").strip()
        if method not in ALLOWED_METHODS or not url:
            continue
        name = str(item.get("name") or "").strip() or url
        rows.append(ApiRow(
            name=name,
            method=method,
            url=url,
            request_params=_as_text(item.get("request_params")),
            response_params=_as_text(item.get("response_params")),
            source_file=str(item.get("source_file") or "").strip(),
        ))
    return rows


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def dedupe_rows(rows: list[ApiRow]) -> list[ApiRow]:
    merged = {}
    order = []
    for row in rows:
        key = (row.method, row.url)
        if key not in merged:
            merged[key] = ApiRow(
                name=row.name,
                method=row.method,
                url=row.url,
                request_params=row.request_params,
                response_params=row.response_params,
                source_file=row.source_file,
            )
            order.append(key)
            continue
        current = merged[key]
        if not current.request_params and row.request_params:
            current.request_params = row.request_params
        if not current.response_params and row.response_params:
            current.response_params = row.response_params
        files = [part for part in current.source_file.split(",") if part]
        if row.source_file and row.source_file not in files:
            files.append(row.source_file)
        current.source_file = ",".join(files)
    return [merged[key] for key in order]


def call_model(config, chunks: list[FileChunk]) -> str:
    from apps.requirement_analysis.models import AIModelService

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": render_batch(chunks)},
    ]

    async def _limited():
        return await asyncio.wait_for(
            AIModelService.call_openai_compatible_api(config, messages),
            timeout=MODEL_CALL_TIMEOUT_SECONDS,
        )

    try:
        result = asyncio.run(_limited())
    except TimeoutError as exc:
        raise TimeoutError("模型调用超时") from exc
    return result["choices"][0]["message"]["content"]


def call_model_with_retry(config, chunks: list[FileChunk]) -> list[ApiRow]:
    last_error = None
    for _ in range(2):
        try:
            return parse_api_rows(call_model(config, chunks))
        except Exception as exc:
            last_error = exc
    raise ModelCallError(f"模型调用失败: {last_error}")

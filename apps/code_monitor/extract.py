import asyncio
import json
import logging
import re
from dataclasses import dataclass

from apps.code_monitor.batching import FileChunk, render_batch

MODEL_CALL_TIMEOUT_SECONDS = 600
_MAX_SPLIT_DEPTH = 6
_MIN_SPLIT_CHARS = 800

logger = logging.getLogger(__name__)
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)
_TRAILING_COMMA = re.compile(r",(\s*[\]}])")

EXCEL_HEADERS = ["名称", "请求方式", "请求地址", "入参", "测试数据", "测试要点", "出参", "源文件"]
ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}


# SYSTEM_PROMPT = """你是前端接口提取器。下面每段代码以「文件: <路径>」开头。只提取这些前端代码发起的 HTTP 请求（如 fetch、axios、request、api client 调用等），不要提取后端路由定义。

# 只输出一个 JSON 数组，不要 Markdown，不要解释。

# 数组每个元素必须是对象，字段如下：
# - name: 字符串。接口名称；看不出时用 url
# - method: 字符串。必须是 GET、POST、PUT、PATCH、DELETE、HEAD、OPTIONS 之一
# - url: 字符串。请求地址（可含路径参数占位，如 /user/:id）
# - request_params: JSON 对象。请求入参结构。键为参数名，值为类型或简短说明（如 "string"、"number"、"boolean"、"object"、"array"，或嵌套对象）。从函数参数、请求体、query、类型定义、接口注释中提取；看不出字段时用 {}
# - response_params: JSON 对象。响应出参结构。键为字段名，值为类型或简短说明，可嵌套。从 .then、解构赋值、类型定义、接口注释中提取；看不出字段时用 {}
# - source_file: 字符串。原样复制该接口所在片段开头的「文件:」后的路径，不能为空

# 规则：
# 1. 不要编造代码里没有的接口或字段。
# 2. request_params、response_params 必须是 JSON 对象，禁止用字符串描述。
# 3. 同一 url+method 出现多次时合并为一条，参数取并集。
# 4. 没有接口时输出 []。"""

SYSTEM_PROMPT = """你是客户端接口提取器。下面每段代码以「文件: <路径>」开头。只提取这些代码发起的 HTTP 请求，包括 Web 前端（fetch、axios、request、api client）、Flutter（Dio、http、Retrofit）和 iOS（URLSession、Alamofire、Moya）。不要提取后端路由定义。

只输出一个 JSON 数组，不要 Markdown，不要解释。

数组每个元素必须是对象，字段如下：
- name: 字符串。接口名称；看不出时用 url
- method: 字符串。必须是 GET、POST、PUT、PATCH、DELETE、HEAD、OPTIONS 之一
- url: 字符串。请求地址（可含路径参数占位，如 /user/:id）
- request_params: JSON 对象，固定三层，缺省用空对象：
  {
    "query": {},
    "body": {},
    "headers": {}
  }
  query / body / headers 内：键为参数名，值为类型或简短说明（如 "string"、"number"、"boolean"、"object"、"array"，或嵌套对象）。从 URL 查询串、函数参数、请求体、headers 配置、类型定义、接口注释中提取；某层看不出字段时保留 {}
- response_params: JSON 对象。响应出参结构。键为字段名，值为类型或简短说明，可嵌套。从返回值、响应体类型、.then、解构赋值、类型定义、接口注释中提取；看不出字段时用 {}
- source_file: 字符串。原样复制该接口所在片段开头的「文件:」后的路径，不能为空

规则：
1. 不要编造代码里没有的接口或字段。
2. request_params 必须始终包含 query、body、headers 三个键，且三者都必须是 JSON 对象；response_params 必须是 JSON 对象。禁止用字符串描述参数。
3. 路径参数（如 :id）写入 query，键名与占位符一致（如 "id": "string"）。
4. Content-Type 等显式写出的请求头放入 headers；未写出则 headers 为 {}。
5. 同一 url+method 出现多次时合并为一条，各层参数取并集。
6. 没有接口时输出 []。
7. 参数值仍以类型开头。代码或注释里能直接看出的约束跟在类型后面，看不出不要写：required、optional、unique、min=数字、max=数字、maxLength=数字，枚举用竖线连接。示例："string, required, unique"、"number, min=0, max=100"、"string, optional, 待支付|已支付|已退款"。不要编造代码里没有的约束。"""

class ModelCallError(Exception):
    pass


class TruncatedModelOutput(Exception):
    def __init__(self, content: str = ""):
        super().__init__("模型输出被截断")
        self.content = content


@dataclass
class ApiRow:
    name: str
    method: str
    url: str
    request_params: str
    response_params: str
    source_file: str


def _strip_model_wrapper(raw: str) -> str:
    text = (raw or "").strip()
    text = _THINK_BLOCK.sub("", text).strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _relax_json(text: str) -> str:
    previous = None
    current = text
    while current != previous:
        previous = current
        current = _TRAILING_COMMA.sub(r"\1", current)
    return current


def _first_json_array(text: str) -> str:
    start = None
    depth = 0
    in_string = False
    escape = False
    for index, char in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "[":
            if depth == 0:
                start = index
            depth += 1
        elif char == "]" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                return text[start:index + 1]
    return ""


def _candidate_payloads(raw: str):
    text = _strip_model_wrapper(raw)
    candidates = []
    for item in (text, _relax_json(text)):
        if item and item not in candidates:
            candidates.append(item)
    extracted = _first_json_array(text)
    if extracted:
        for item in (extracted, _relax_json(extracted)):
            if item and item not in candidates:
                candidates.append(item)
    return candidates


def _load_json_array(raw: str):
    for candidate in _candidate_payloads(raw):
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, list):
            return payload
    raise ValueError("模型返回的内容不是合法 JSON 数组")


def _is_truncated_json_array(raw: str) -> bool:
    text = _strip_model_wrapper(raw)
    if "[" not in text or _first_json_array(text):
        return False
    return True


def _halve_chunks(chunks: list[FileChunk]):
    if len(chunks) >= 2:
        mid = len(chunks) // 2
        return chunks[:mid], chunks[mid:]
    chunk = chunks[0]
    if len(chunk.text) < _MIN_SPLIT_CHARS:
        return None
    midpoint = len(chunk.text) // 2
    newline = chunk.text.rfind("\n", 0, midpoint)
    if newline > 0:
        midpoint = newline + 1
    left, right = chunk.text[:midpoint], chunk.text[midpoint:]
    if not left.strip() or not right.strip():
        return None
    return [FileChunk(chunk.source_file, left)], [FileChunk(chunk.source_file, right)]


def parse_api_rows(raw: str) -> list[ApiRow]:
    payload = _load_json_array(raw)
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
            AIModelService.call_openai_compatible_api(config, messages, max_tokens=8192),
            timeout=MODEL_CALL_TIMEOUT_SECONDS,
        )

    try:
        result = asyncio.run(_limited())
    except TimeoutError as exc:
        raise TimeoutError("模型调用超时") from exc
    choice = result["choices"][0]
    message = choice.get("message") or {}
    content = message.get("content") or ""
    if not str(content).strip():
        content = message.get("reasoning_content") or ""
    content = str(content)
    if choice.get("finish_reason") == "length":
        try:
            parse_api_rows(content)
        except ValueError:
            raise TruncatedModelOutput(content)
    return content


def _match_source_file(reported: str, known: list[str]) -> str:
    text = (reported or "").replace("\\", "/").strip()
    if text in known:
        return text
    hits = [name for name in known if text and (name.endswith("/" + text) or name.endswith(text))]
    if len(hits) == 1:
        return hits[0]
    return ""


def stamp_source_files(rows: list[ApiRow], chunks: list[FileChunk]) -> list[ApiRow]:
    known = list(dict.fromkeys(chunk.source_file for chunk in chunks if chunk.source_file))
    if not known:
        return rows
    if len(known) == 1:
        for row in rows:
            row.source_file = known[0]
        return rows
    for row in rows:
        row.source_file = _match_source_file(row.source_file, known) or row.source_file or ",".join(known)
    return rows


def _extract_smaller(config, chunks: list[FileChunk], depth: int) -> list[ApiRow] | None:
    if depth >= _MAX_SPLIT_DEPTH:
        return None
    parts = _halve_chunks(chunks)
    if not parts:
        return None
    logger.warning(
        "code monitor model output truncated, splitting batch: files=%s chars=%s",
        len(chunks),
        sum(len(chunk.text) for chunk in chunks),
    )
    left, right = parts
    return (
        call_model_with_retry(config, left, _depth=depth + 1)
        + call_model_with_retry(config, right, _depth=depth + 1)
    )


def call_model_with_retry(config, chunks: list[FileChunk], _depth: int = 0) -> list[ApiRow]:
    last_error = None
    for _ in range(2):
        try:
            raw = call_model(config, chunks)
        except TruncatedModelOutput as exc:
            smaller = _extract_smaller(config, chunks, _depth)
            if smaller is not None:
                return smaller
            last_error = exc
            continue
        except Exception as exc:
            last_error = exc
            continue
        if _is_truncated_json_array(raw):
            smaller = _extract_smaller(config, chunks, _depth)
            if smaller is not None:
                return smaller
        try:
            return stamp_source_files(parse_api_rows(raw), chunks)
        except Exception as exc:
            last_error = exc
    raise ModelCallError(f"模型调用失败: {last_error}")

# 代码监控：提取 API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 首页增加「代码监控」卡片；打开后在「提取 API」下管理代码地址、发起扫描，并把源码中的接口导出为 Excel。

**Architecture:** 纯函数负责筛文件、分批、解析去重和写 Excel。Django 应用 `apps/code_monitor` 保存地址和扫描任务，Celery 任务取代码并调用现有的 OpenAI 兼容模型。前端是首页卡片加一个三栏目页面。检查代码质量只出现在卡片说明里。

**Tech Stack:** Django 4.2、DRF、Celery、openpyxl、现有 `AIModelService`、Vue 3、Element Plus、vue-i18n。

## Global Constraints

- 卡片标题为「代码监控」。说明为「支持从源代码中提取 API，也支持从源代码中检查代码质量」。英文标题为 “Code Monitoring”，说明为 “Extract APIs from source code, and check code quality from source code.”
- 路由是 `/code-monitor`，点击首页卡片后新标签打开。
- 页面父栏目只有「提取 API」。子栏目是「代码地址」「扫描任务」「下载结果」。不做检查代码质量的栏目和功能。
- 不按技术栈写解析器。模型只根据给定代码输出 JSON，禁止补写代码里没有的接口和字段。
- 只读源码。不安装依赖，不运行项目。
- 不因仓库体积或候选文件数量拒绝任务。
- 每批输入不超过 60000 个字符。单个文件超过上限时按行切开，文件内容不丢弃。
- 克隆或解压限时 10 分钟。
- 访问令牌不写入地址、任务字段和日志。任务进入成功或失败后删除上传的 zip，只保留 Excel。
- 临时目录在任务结束时删除。
- 模型某一批失败则重试一次。仍失败则整次任务失败，不写入 Excel。
- 没有请求方式或请求地址的条目丢掉。同一请求方式和地址只留一行。入参、出参保留先得到的非空内容。源文件用逗号拼路径。
- Excel 列顺序：名称、请求方式、请求地址、入参、出参、源文件。
- 没有候选文件时失败，原因是「没有找到像接口定义的文件」。
- 地址、任务、结果只显示当前登录用户自己的。
- 没有已启用的模型配置时不能提交扫描。
- 复用现有 AI 模型配置和 Celery。不写入 API 测试模块。

---

## File Structure

- Create: `apps/code_monitor/__init__.py` — 包标记
- Create: `apps/code_monitor/apps.py` — 应用配置
- Create: `apps/code_monitor/screening.py` — 整棵目录筛候选文件
- Create: `apps/code_monitor/batching.py` — 按 60000 字符切批
- Create: `apps/code_monitor/extract.py` — 提示词、模型调用、解析、去重
- Create: `apps/code_monitor/excel_export.py` — 写 xlsx 字节
- Create: `apps/code_monitor/acquire.py` — 克隆、解压、清理
- Create: `apps/code_monitor/pipeline.py` — 一次扫描的编排
- Create: `apps/code_monitor/models.py` — 代码地址、扫描任务
- Create: `apps/code_monitor/serializers.py` — 入参与出参，不含令牌
- Create: `apps/code_monitor/views.py` — 地址与任务接口
- Create: `apps/code_monitor/urls.py` — `/api/code-monitor/`
- Create: `apps/code_monitor/tasks.py` — Celery 入口
- Create: `apps/code_monitor/tests/test_screening.py`
- Create: `apps/code_monitor/tests/test_batching.py`
- Create: `apps/code_monitor/tests/test_extract.py`
- Create: `apps/code_monitor/tests/test_excel_export.py`
- Create: `apps/code_monitor/tests/test_acquire.py`
- Create: `apps/code_monitor/tests/test_pipeline.py`
- Create: `apps/code_monitor/tests/test_api.py`
- Modify: `backend/settings.py` — 注册应用
- Modify: `backend/urls.py` — 挂上路由
- Create: `frontend/src/api/code-monitor.js`
- Create: `frontend/src/views/code-monitor/CodeMonitor.vue`
- Modify: `frontend/src/views/Home.vue` — 首页卡片
- Modify: `frontend/src/router/index.js` — `/code-monitor`
- Modify: `frontend/src/locales/lang/zh-cn/project.js`
- Modify: `frontend/src/locales/lang/en/project.js`

---

### Task 1: 筛文件

**Files:**
- Create: `apps/code_monitor/__init__.py`
- Create: `apps/code_monitor/screening.py`
- Test: `apps/code_monitor/tests/test_screening.py`

**Interfaces:**
- Consumes: 一个已解压的目录 `pathlib.Path`
- Produces: `select_candidate_files(root: Path) -> list[Path]`，返回按路径排序的绝对路径

- [ ] **Step 1: Write the failing test**

`apps/code_monitor/tests/test_screening.py`：

```python
from pathlib import Path

from apps.code_monitor.screening import select_candidate_files


def _write(path: Path, text: str = "x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_skips_dependency_build_and_binary(tmp_path: Path):
    _write(tmp_path / "node_modules" / "lib" / "api.js", "axios.get('/skip')")
    _write(tmp_path / "venv" / "views.py", "urlpatterns = []")
    _write(tmp_path / ".venv" / "urls.py", "urlpatterns = []")
    _write(tmp_path / "dist" / "controller.js", "fetch('/skip')")
    _write(tmp_path / "build" / "router.js", "app.get('/skip')")
    _write(tmp_path / ".git" / "config", "api")
    _write(tmp_path / "pkg" / "__pycache__" / "views.py", "urlpatterns = []")
    _write(tmp_path / "package-lock.json", "axios")
    _write(tmp_path / "yarn.lock", "axios")
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\r\n")
    kept = select_candidate_files(tmp_path)
    assert kept == []


def test_keeps_path_or_content_match(tmp_path: Path):
    _write(tmp_path / "src" / "api" / "client.js", "export const x = 1")
    _write(tmp_path / "src" / "plain.js", "axios.get('/orders')")
    _write(tmp_path / "readme.txt", "this file has no interface")
    kept = [p.relative_to(tmp_path).as_posix() for p in select_candidate_files(tmp_path)]
    assert kept == ["src/api/client.js", "src/plain.js"]


def test_content_keywords(tmp_path: Path):
    samples = {
        "a.js": "fetch('/a')",
        "b.py": "urlpatterns = []",
        "c.java": "@GetMapping('/c')",
        "d.java": "@PostMapping('/d')",
        "e.java": "@PutMapping('/e')",
        "f.java": "@DeleteMapping('/f')",
        "g.java": "@PatchMapping('/g')",
        "h.js": "app.get('/h')",
        "i.js": "app.post('/i')",
        "j.js": "app.put('/j')",
        "k.js": "app.delete('/k')",
        "l.js": "router.get('/l')",
        "m.js": "router.post('/m')",
        "n.js": "router.put('/n')",
        "o.js": "router.delete('/o')",
    }
    for name, text in samples.items():
        _write(tmp_path / name, text)
    kept = {p.name for p in select_candidate_files(tmp_path)}
    assert kept == set(samples)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/code_monitor/tests/test_screening.py -v`

Expected: FAIL with `ModuleNotFoundError` for `apps.code_monitor.screening`

- [ ] **Step 3: Write minimal implementation**

`apps/code_monitor/__init__.py` 为空文件。

`apps/code_monitor/screening.py`：

```python
from pathlib import Path

SKIP_DIR_NAMES = {
    ".git",
    "node_modules",
    "venv",
    ".venv",
    "dist",
    "build",
    "__pycache__",
}
LOCK_FILE_NAMES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "Pipfile.lock",
    "Cargo.lock",
    "composer.lock",
}
BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico",
    ".zip", ".tar", ".gz", ".7z", ".jar", ".war",
    ".pdf", ".mp4", ".mp3", ".woff", ".woff2", ".ttf", ".eot",
    ".exe", ".dll", ".so", ".pyc", ".class",
}
PATH_KEYWORDS = (
    "api", "router", "controller", "views", "urls", "serializer", "route",
)
CONTENT_KEYWORDS = (
    "axios", "fetch", "urlpatterns",
    "@GetMapping", "@PostMapping", "@PutMapping", "@DeleteMapping", "@PatchMapping",
    "app.get", "app.post", "app.put", "app.delete",
    "router.get", "router.post", "router.put", "router.delete",
)


def select_candidate_files(root: Path) -> list[Path]:
    kept = []
    for path in _walk(root):
        if _path_matches(path, root) or _content_matches(path):
            kept.append(path)
    return sorted(kept)


def _walk(root: Path):
    for dirpath, dirnames, filenames in os_walk(root):
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIR_NAMES]
        for filename in filenames:
            path = Path(dirpath) / filename
            if _skipped_file(path):
                continue
            yield path


def os_walk(root: Path):
    import os
    return os.walk(root)


def _skipped_file(path: Path) -> bool:
    name = path.name
    if name in LOCK_FILE_NAMES or name.endswith(".lock"):
        return True
    if path.suffix.lower() in BINARY_SUFFIXES:
        return True
    return False


def _path_matches(path: Path, root: Path) -> bool:
    relative = path.relative_to(root).as_posix().casefold()
    return any(keyword in relative for keyword in PATH_KEYWORDS)


def _content_matches(path: Path) -> bool:
    try:
        chunk = path.read_bytes()[:8192]
    except OSError:
        return False
    if b"\x00" in chunk:
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return any(keyword in text for keyword in CONTENT_KEYWORDS)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest apps/code_monitor/tests/test_screening.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/code_monitor/__init__.py apps/code_monitor/screening.py apps/code_monitor/tests/test_screening.py
git commit -m "feat: 筛出可能含接口的源码文件"
```

---

### Task 2: 按字符分批

**Files:**
- Create: `apps/code_monitor/batching.py`
- Test: `apps/code_monitor/tests/test_batching.py`

**Interfaces:**
- Consumes: `select_candidate_files` 返回的绝对路径，以及扫描根目录
- Produces:
  - `MAX_BATCH_CHARS = 60000`
  - `FileChunk(source_file: str, text: str)`，`source_file` 是相对根目录的 posix 路径
  - `split_into_batches(files: list[Path], root: Path, max_chars: int = MAX_BATCH_CHARS) -> list[list[FileChunk]]`

- [ ] **Step 1: Write the failing test**

`apps/code_monitor/tests/test_batching.py`：

```python
from pathlib import Path

from apps.code_monitor.batching import MAX_BATCH_CHARS, split_into_batches


def test_default_budget_is_60000():
    assert MAX_BATCH_CHARS == 60000


def test_packs_small_files_until_budget(tmp_path: Path):
    one = tmp_path / "a.js"
    two = tmp_path / "b.js"
    one.write_text("a" * 30, encoding="utf-8")
    two.write_text("b" * 30, encoding="utf-8")
    batches = split_into_batches([one, two], tmp_path, max_chars=80)
    assert len(batches) == 1
    assert [chunk.source_file for chunk in batches[0]] == ["a.js", "b.js"]


def test_splits_a_long_file_without_dropping_characters(tmp_path: Path):
    path = tmp_path / "long.js"
    text = "\n".join(f"line-{i}" for i in range(20))
    path.write_text(text, encoding="utf-8")
    batches = split_into_batches([path], tmp_path, max_chars=40)
    joined = "".join(chunk.text for batch in batches for chunk in batch)
    assert joined == text
    assert all(len(chunk.text) <= 40 for batch in batches for chunk in batch)
    assert all(chunk.source_file == "long.js" for batch in batches for chunk in batch)


def test_splits_a_single_line_longer_than_budget(tmp_path: Path):
    path = tmp_path / "wide.js"
    path.write_text("z" * 25, encoding="utf-8")
    batches = split_into_batches([path], tmp_path, max_chars=10)
    joined = "".join(chunk.text for batch in batches for chunk in batch)
    assert joined == "z" * 25
    assert all(len(chunk.text) <= 10 for batch in batches for chunk in batch)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/code_monitor/tests/test_batching.py -v`

Expected: FAIL with `ModuleNotFoundError` for `apps.code_monitor.batching`

- [ ] **Step 3: Write minimal implementation**

`apps/code_monitor/batching.py`：

```python
from dataclasses import dataclass
from pathlib import Path

MAX_BATCH_CHARS = 60000


@dataclass
class FileChunk:
    source_file: str
    text: str


def split_into_batches(files: list[Path], root: Path, max_chars: int = MAX_BATCH_CHARS) -> list[list[FileChunk]]:
    chunks = []
    for path in files:
        relative = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        chunks.extend(_slice_text(relative, text, max_chars))
    return _pack(chunks, max_chars)


def _slice_text(source_file: str, text: str, max_chars: int) -> list[FileChunk]:
    if len(text) <= max_chars:
        return [FileChunk(source_file, text)] if text else []
    pieces = []
    buf = []
    size = 0
    for line in text.splitlines(keepends=True):
        start = 0
        while start < len(line):
            room = max_chars - size
            if room <= 0 and buf:
                pieces.append(FileChunk(source_file, "".join(buf)))
                buf = []
                size = 0
                room = max_chars
            take = line[start:start + room]
            buf.append(take)
            size += len(take)
            start += len(take)
            if size >= max_chars:
                pieces.append(FileChunk(source_file, "".join(buf)))
                buf = []
                size = 0
    if buf:
        pieces.append(FileChunk(source_file, "".join(buf)))
    return pieces


def _pack(chunks: list[FileChunk], max_chars: int) -> list[list[FileChunk]]:
    batches = []
    current = []
    size = 0
    for chunk in chunks:
        if current and size + len(chunk.text) > max_chars:
            batches.append(current)
            current = []
            size = 0
        current.append(chunk)
        size += len(chunk.text)
    if current:
        batches.append(current)
    return batches
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest apps/code_monitor/tests/test_batching.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/code_monitor/batching.py apps/code_monitor/tests/test_batching.py
git commit -m "feat: 按字符预算把候选文件切成批次"
```

---

### Task 3: 解析、去重和模型调用

**Files:**
- Create: `apps/code_monitor/extract.py`
- Test: `apps/code_monitor/tests/test_extract.py`

**Interfaces:**
- Consumes: `FileChunk`；`AIModelService.call_openai_compatible_api(config, messages)`
- Produces:
  - `ApiRow(name, method, url, request_params, response_params, source_file)`，六个字段都是 `str`
  - `EXCEL_HEADERS`
  - `parse_api_rows(raw: str) -> list[ApiRow]`，顶层不是 JSON 数组时抛 `ValueError`
  - `dedupe_rows(rows: list[ApiRow]) -> list[ApiRow]`
  - `call_model(config, chunks: list[FileChunk]) -> str`
  - `call_model_with_retry(config, chunks: list[FileChunk]) -> list[ApiRow]`，失败两次后抛 `ModelCallError`

- [ ] **Step 1: Write the failing test**

`apps/code_monitor/tests/test_extract.py`：

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/code_monitor/tests/test_extract.py -v`

Expected: FAIL with `ModuleNotFoundError` for `apps.code_monitor.extract`

- [ ] **Step 3: Write minimal implementation**

`apps/code_monitor/extract.py`：

```python
import asyncio
import json
from dataclasses import dataclass

from apps.code_monitor.batching import FileChunk

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
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
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


def render_batch(chunks: list[FileChunk]) -> str:
    parts = []
    for chunk in chunks:
        parts.append(f"文件: {chunk.source_file}\n{chunk.text}")
    return "\n\n".join(parts)


def call_model(config, chunks: list[FileChunk]) -> str:
    from apps.requirement_analysis.models import AIModelService

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": render_batch(chunks)},
    ]
    result = asyncio.run(AIModelService.call_openai_compatible_api(config, messages))
    return result["choices"][0]["message"]["content"]


def call_model_with_retry(config, chunks: list[FileChunk]) -> list[ApiRow]:
    last_error = None
    for _ in range(2):
        try:
            return parse_api_rows(call_model(config, chunks))
        except Exception as exc:
            last_error = exc
    raise ModelCallError(f"模型调用失败: {last_error}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest apps/code_monitor/tests/test_extract.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/code_monitor/extract.py apps/code_monitor/tests/test_extract.py
git commit -m "feat: 解析模型返回的接口并按方法与地址去重"
```

---

### Task 4: 写 Excel

**Files:**
- Create: `apps/code_monitor/excel_export.py`
- Test: `apps/code_monitor/tests/test_excel_export.py`

**Interfaces:**
- Consumes: `list[ApiRow]`、`EXCEL_HEADERS`
- Produces: `write_api_workbook(rows: list[ApiRow]) -> bytes`

- [ ] **Step 1: Write the failing test**

`apps/code_monitor/tests/test_excel_export.py`：

```python
from io import BytesIO

from openpyxl import load_workbook

from apps.code_monitor.excel_export import write_api_workbook
from apps.code_monitor.extract import EXCEL_HEADERS, ApiRow


def test_workbook_column_order_and_values():
    content = write_api_workbook([
        ApiRow("列表", "GET", "/api/items", "page", "id,name", "src/api/items.js"),
    ])
    sheet = load_workbook(BytesIO(content)).active
    assert [cell.value for cell in sheet[1]] == EXCEL_HEADERS
    assert [cell.value for cell in sheet[2]] == [
        "列表", "GET", "/api/items", "page", "id,name", "src/api/items.js",
    ]


def test_empty_rows_still_have_header():
    sheet = load_workbook(BytesIO(write_api_workbook([]))).active
    assert [cell.value for cell in sheet[1]] == EXCEL_HEADERS
    assert sheet.max_row == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/code_monitor/tests/test_excel_export.py -v`

Expected: FAIL with `ModuleNotFoundError` for `apps.code_monitor.excel_export`

- [ ] **Step 3: Write minimal implementation**

`apps/code_monitor/excel_export.py`：

```python
from io import BytesIO

from openpyxl import Workbook

from apps.code_monitor.extract import EXCEL_HEADERS, ApiRow


def write_api_workbook(rows: list[ApiRow]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "API"
    sheet.append(EXCEL_HEADERS)
    for row in rows:
        sheet.append([
            row.name,
            row.method,
            row.url,
            row.request_params,
            row.response_params,
            row.source_file,
        ])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest apps/code_monitor/tests/test_excel_export.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/code_monitor/excel_export.py apps/code_monitor/tests/test_excel_export.py
git commit -m "feat: 把提取出的接口写成 Excel"
```

---

### Task 5: 取代码

**Files:**
- Create: `apps/code_monitor/acquire.py`
- Test: `apps/code_monitor/tests/test_acquire.py`

**Interfaces:**
- Consumes: Git 地址或 zip 路径，可选令牌
- Produces:
  - `FETCH_TIMEOUT_SECONDS = 600`
  - `AcquireError`
  - `clone_repository(url: str, dest: Path, token: str = "", timeout: int = FETCH_TIMEOUT_SECONDS) -> None`
  - `unzip_archive(archive_path: Path, dest: Path) -> None`
  - `redact(text: str, token: str) -> str`

- [ ] **Step 1: Write the failing test**

`apps/code_monitor/tests/test_acquire.py`：

```python
import subprocess
import zipfile
from pathlib import Path

import pytest

from apps.code_monitor.acquire import (
    FETCH_TIMEOUT_SECONDS,
    AcquireError,
    clone_repository,
    redact,
    unzip_archive,
)


def test_timeout_constant():
    assert FETCH_TIMEOUT_SECONDS == 600


def test_token_is_not_part_of_the_git_command(tmp_path: Path, monkeypatch):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["env"] = kwargs.get("env") or {}
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("apps.code_monitor.acquire.subprocess.run", fake_run)
    clone_repository("https://example.com/repo.git", tmp_path / "repo", token="super-secret-token")
    assert "super-secret-token" not in " ".join(seen["cmd"])
    assert seen["env"]["GIT_CONFIG_VALUE_0"] == "Authorization: Bearer super-secret-token"


def test_clone_timeout_becomes_acquire_error(tmp_path: Path, monkeypatch):
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))

    monkeypatch.setattr("apps.code_monitor.acquire.subprocess.run", fake_run)
    with pytest.raises(AcquireError, match="克隆或解压超时"):
        clone_repository("https://example.com/repo.git", tmp_path / "repo", token="super-secret-token")


def test_redact_removes_token():
    assert redact("failed super-secret-token", "super-secret-token") == "failed ***"


def test_unzip_rejects_path_escape(tmp_path: Path):
    archive = tmp_path / "bad.zip"
    dest = tmp_path / "out"
    dest.mkdir()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../outside.txt", "nope")
    with pytest.raises(AcquireError, match="压缩包路径不安全"):
        unzip_archive(archive, dest)
    assert not (tmp_path / "outside.txt").exists()


def test_unzip_extracts_safe_files(tmp_path: Path):
    archive = tmp_path / "ok.zip"
    dest = tmp_path / "out"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("src/api.js", "axios.get('/api/a')")
    unzip_archive(archive, dest)
    assert (dest / "src" / "api.js").read_text(encoding="utf-8") == "axios.get('/api/a')"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/code_monitor/tests/test_acquire.py -v`

Expected: FAIL with `ModuleNotFoundError` for `apps.code_monitor.acquire`

- [ ] **Step 3: Write minimal implementation**

`apps/code_monitor/acquire.py`：

```python
import subprocess
import zipfile
from pathlib import Path

FETCH_TIMEOUT_SECONDS = 600


class AcquireError(Exception):
    pass


def redact(text: str, token: str) -> str:
    if token and text and token in text:
        return text.replace(token, "***")
    return text or ""


def clone_repository(url: str, dest: Path, token: str = "", timeout: int = FETCH_TIMEOUT_SECONDS) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["git", "clone", "--depth", "1", url, str(dest)]
    env = dict(**__import__("os").environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    if token:
        env["GIT_CONFIG_COUNT"] = "1"
        env["GIT_CONFIG_KEY_0"] = "http.extraheader"
        env["GIT_CONFIG_VALUE_0"] = f"Authorization: Bearer {token}"
    try:
        subprocess.run(
            cmd,
            env=env,
            timeout=timeout,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired as exc:
        raise AcquireError("克隆或解压超时") from exc
    except subprocess.CalledProcessError as exc:
        detail = redact((exc.stderr or exc.stdout or "").strip(), token)
        raise AcquireError(f"取代码失败: {detail or 'git clone 失败'}") from exc


def unzip_archive(archive_path: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(archive_path) as zf:
            dest_resolved = dest.resolve()
            for info in zf.infolist():
                target = (dest_resolved / info.filename).resolve()
                try:
                    target.relative_to(dest_resolved)
                except ValueError:
                    raise AcquireError("压缩包路径不安全")
            zf.extractall(dest)
    except AcquireError:
        raise
    except (zipfile.BadZipFile, OSError) as exc:
        raise AcquireError("取代码失败: zip 打不开") from exc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest apps/code_monitor/tests/test_acquire.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/code_monitor/acquire.py apps/code_monitor/tests/test_acquire.py
git commit -m "feat: 克隆仓库或解压上传代码"
```

---

### Task 6: 数据模型和路由注册

**Files:**
- Create: `apps/code_monitor/apps.py`
- Create: `apps/code_monitor/models.py`
- Modify: `backend/settings.py` 的 `LOCAL_APPS`
- Modify: `backend/urls.py`
- Create: `apps/code_monitor/migrations/0001_initial.py`（由命令生成）
- Test: `apps/code_monitor/tests/test_api.py` 里先只放模型约束测试，接口留到 Task 8

**Interfaces:**
- Consumes: `apps.users.User`、`requirement_analysis.AIModelConfig`
- Produces:
  - `CodeAddress(name, git_url, created_by, created_at)`
  - `ScanTask` 字段：`source_type`（`git` / `zip`）、`git_url`、`archive`、`model_config`、`status`（`pending` / `running` / `succeeded` / `failed`）、`progress`、`error_message`、`celery_task_id`、`result_file`、`created_by`、`created_at`、`updated_at`
  - 两个模型都没有令牌字段

- [ ] **Step 1: Write the failing test**

在 `apps/code_monitor/tests/test_api.py` 写入：

```python
import pytest

from apps.code_monitor.models import CodeAddress, ScanTask

pytestmark = pytest.mark.django_db


def test_models_have_no_token_field():
    address_fields = {field.name for field in CodeAddress._meta.fields}
    task_fields = {field.name for field in ScanTask._meta.fields}
    assert "token" not in address_fields
    assert "token" not in task_fields
    assert {"name", "git_url", "created_by"}.issubset(address_fields)
    assert {
        "source_type", "git_url", "archive", "model_config", "status",
        "progress", "error_message", "celery_task_id", "result_file", "created_by",
    }.issubset(task_fields)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/code_monitor/tests/test_api.py::test_models_have_no_token_field -v`

Expected: FAIL with `ImportError` for `apps.code_monitor.models`

- [ ] **Step 3: Write minimal implementation**

`apps/code_monitor/apps.py`：

```python
from django.apps import AppConfig


class CodeMonitorConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.code_monitor"
    verbose_name = "代码监控"
```

`apps/code_monitor/models.py`：

```python
from django.conf import settings
from django.db import models


class CodeAddress(models.Model):
    name = models.CharField(max_length=200, verbose_name="名称")
    git_url = models.CharField(max_length=500, verbose_name="Git 地址")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="code_monitor_addresses",
        verbose_name="创建者",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        db_table = "code_monitor_addresses"
        ordering = ["-created_at"]


class ScanTask(models.Model):
    SOURCE_GIT = "git"
    SOURCE_ZIP = "zip"
    SOURCE_CHOICES = [
        (SOURCE_GIT, "Git"),
        (SOURCE_ZIP, "zip"),
    ]
    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_SUCCEEDED = "succeeded"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "待执行"),
        (STATUS_RUNNING, "执行中"),
        (STATUS_SUCCEEDED, "成功"),
        (STATUS_FAILED, "失败"),
    ]

    source_type = models.CharField(max_length=10, choices=SOURCE_CHOICES, verbose_name="来源类型")
    git_url = models.CharField(max_length=500, blank=True, default="", verbose_name="Git 地址")
    archive = models.FileField(upload_to="code_monitor/archives/", null=True, blank=True, verbose_name="上传的 zip")
    model_config = models.ForeignKey(
        "requirement_analysis.AIModelConfig",
        on_delete=models.PROTECT,
        related_name="code_monitor_tasks",
        verbose_name="AI 模型配置",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, verbose_name="状态")
    progress = models.PositiveSmallIntegerField(default=0, verbose_name="进度")
    error_message = models.TextField(blank=True, default="", verbose_name="失败原因")
    celery_task_id = models.CharField(max_length=100, blank=True, default="", verbose_name="Celery 任务 ID")
    result_file = models.FileField(upload_to="code_monitor/results/", null=True, blank=True, verbose_name="结果 Excel")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="code_monitor_tasks",
        verbose_name="创建者",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "code_monitor_tasks"
        ordering = ["-created_at"]
```

`backend/settings.py` 的 `LOCAL_APPS` 末尾、`apps.mcp.apps.McpConfig` 之后追加：

```python
    'apps.code_monitor.apps.CodeMonitorConfig',
```

`backend/urls.py` 的 `urlpatterns` 里、其他 `path('api/...')` 旁边追加：

```python
    path('api/code-monitor/', include('apps.code_monitor.urls')),
```

先放一个空路由，避免应用尚未完成视图时 Django 检查失败。`apps/code_monitor/urls.py`：

```python
urlpatterns = []
```

然后生成迁移：

Run: `python manage.py makemigrations code_monitor`

Expected: 新建 `apps/code_monitor/migrations/0001_initial.py`

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest apps/code_monitor/tests/test_api.py::test_models_have_no_token_field -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/code_monitor/apps.py apps/code_monitor/models.py apps/code_monitor/urls.py apps/code_monitor/migrations backend/settings.py backend/urls.py apps/code_monitor/tests/test_api.py
git commit -m "feat: 增加代码监控的地址和扫描任务"
```

---

### Task 7: 扫描编排

**Files:**
- Create: `apps/code_monitor/pipeline.py`
- Create: `apps/code_monitor/tasks.py`
- Test: `apps/code_monitor/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `select_candidate_files`、`split_into_batches`、`call_model_with_retry`、`dedupe_rows`、`write_api_workbook`、`clone_repository`、`unzip_archive`、`redact`、`ScanTask`
- Produces:
  - `execute_scan(task_id: int, token: str = "") -> None`
  - `run_code_monitor_scan(task_id: int)` Celery 任务。令牌从缓存键 `code_monitor_git_token:{task_id}` 读取并立刻删除，不进入 Celery 参数

- [ ] **Step 1: Write the failing test**

`apps/code_monitor/tests/test_pipeline.py`：

```python
import json
import zipfile

import pytest
from django.core.files.base import ContentFile

from apps.code_monitor.models import ScanTask
from apps.code_monitor.pipeline import execute_scan
from apps.requirement_analysis.models import AIModelConfig
from apps.users.models import User

pytestmark = pytest.mark.django_db


def _user():
    return User.objects.create_user(username="scanner", password="pass123456")


def _config(user):
    return AIModelConfig.objects.create(
        name="提取模型",
        model_type="other",
        role="writer",
        base_url="https://example.com/v1",
        model_name="fake",
        created_by=user,
        is_active=True,
    )


def _zip_task(user, config, filename, content):
    archive = zipfile.ZipFile(__import__("io").BytesIO(), "w")
    return archive


def test_success_writes_excel_and_deletes_zip(tmp_path, monkeypatch):
    user = _user()
    config = _config(user)
    buffer = __import__("io").BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("src/api.js", "axios.get('/api/items')")
    task = ScanTask.objects.create(
        source_type=ScanTask.SOURCE_ZIP,
        model_config=config,
        created_by=user,
    )
    task.archive.save("sample.zip", ContentFile(buffer.getvalue()), save=True)

    def fake_call(model_config, chunks):
        assert chunks[0].source_file == "src/api.js"
        return json.dumps([{
            "name": "列表",
            "method": "GET",
            "url": "/api/items",
            "request_params": "page",
            "response_params": "id",
            "source_file": "src/api.js",
        }])

    monkeypatch.setattr("apps.code_monitor.extract.call_model", fake_call)
    execute_scan(task.id, token="super-secret-token")
    task.refresh_from_db()
    assert task.status == ScanTask.STATUS_SUCCEEDED
    assert task.progress == 100
    assert task.result_file
    assert not task.archive
    assert "super-secret-token" not in task.error_message


def test_no_candidate_fails_without_excel():
    user = _user()
    config = _config(user)
    buffer = __import__("io").BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("readme.txt", "hello")
    task = ScanTask.objects.create(
        source_type=ScanTask.SOURCE_ZIP,
        model_config=config,
        created_by=user,
    )
    task.archive.save("empty.zip", ContentFile(buffer.getvalue()), save=True)
    execute_scan(task.id)
    task.refresh_from_db()
    assert task.status == ScanTask.STATUS_FAILED
    assert task.error_message == "没有找到像接口定义的文件"
    assert not task.result_file


def test_invalid_model_json_fails_whole_task_without_excel(monkeypatch):
    user = _user()
    config = _config(user)
    buffer = __import__("io").BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("src/api.js", "axios.get('/api/items')")
    task = ScanTask.objects.create(
        source_type=ScanTask.SOURCE_ZIP,
        model_config=config,
        created_by=user,
    )
    task.archive.save("bad.zip", ContentFile(buffer.getvalue()), save=True)
    monkeypatch.setattr("apps.code_monitor.extract.call_model", lambda config, chunks: "not-json")
    execute_scan(task.id)
    task.refresh_from_db()
    assert task.status == ScanTask.STATUS_FAILED
    assert task.error_message.startswith("模型调用失败")
    assert not task.result_file
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/code_monitor/tests/test_pipeline.py -v`

Expected: FAIL with `ModuleNotFoundError` for `apps.code_monitor.pipeline`

- [ ] **Step 3: Write minimal implementation**

`apps/code_monitor/pipeline.py`：

```python
import shutil
import tempfile
from pathlib import Path

from django.core.files.base import ContentFile

from apps.code_monitor.acquire import AcquireError, clone_repository, redact, unzip_archive
from apps.code_monitor.batching import split_into_batches
from apps.code_monitor.excel_export import write_api_workbook
from apps.code_monitor.extract import call_model_with_retry, dedupe_rows
from apps.code_monitor.models import ScanTask
from apps.code_monitor.screening import select_candidate_files


def execute_scan(task_id: int, token: str = "") -> None:
    task = ScanTask.objects.get(id=task_id)
    task.status = ScanTask.STATUS_RUNNING
    task.error_message = ""
    task.progress = 0
    task.save(update_fields=["status", "error_message", "progress", "updated_at"])
    root = Path(tempfile.mkdtemp(prefix="code_monitor_"))
    try:
        _fill_root(task, root, token)
        files = select_candidate_files(root)
        if not files:
            raise AcquireError("没有找到像接口定义的文件")
        batches = split_into_batches(files, root)
        rows = []
        for index, batch in enumerate(batches, start=1):
            rows.extend(call_model_with_retry(task.model_config, batch))
            task.progress = int(index * 100 / len(batches))
            task.save(update_fields=["progress", "updated_at"])
        content = write_api_workbook(dedupe_rows(rows))
        task.result_file.save(f"api-extract-{task.id}.xlsx", ContentFile(content), save=False)
        task.status = ScanTask.STATUS_SUCCEEDED
        task.progress = 100
        task.error_message = ""
        task.save(update_fields=["result_file", "status", "progress", "error_message", "updated_at"])
    except Exception as exc:
        task.status = ScanTask.STATUS_FAILED
        task.error_message = redact(str(exc), token)[:2000]
        task.result_file.delete(save=False)
        task.save(update_fields=["status", "error_message", "result_file", "updated_at"])
    finally:
        shutil.rmtree(root, ignore_errors=True)
        if task.archive:
            task.archive.delete(save=True)


def _fill_root(task: ScanTask, root: Path, token: str) -> None:
    if task.source_type == ScanTask.SOURCE_GIT:
        clone_repository(task.git_url, root, token=token)
        return
    if not task.archive:
        raise AcquireError("取代码失败: zip 打不开")
    unzip_archive(Path(task.archive.path), root)
```

`apps/code_monitor/tasks.py`：

```python
from celery import shared_task
from django.core.cache import cache

from apps.code_monitor.pipeline import execute_scan


def token_cache_key(task_id: int) -> str:
    return f"code_monitor_git_token:{task_id}"


@shared_task(bind=True)
def run_code_monitor_scan(self, task_id: int):
    from apps.code_monitor.models import ScanTask

    token = cache.get(token_cache_key(task_id)) or ""
    cache.delete(token_cache_key(task_id))
    task = ScanTask.objects.get(id=task_id)
    task.celery_task_id = self.request.id or ""
    task.save(update_fields=["celery_task_id", "updated_at"])
    execute_scan(task_id, token=token)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest apps/code_monitor/tests/test_pipeline.py -v`

Expected: PASS。成功用例的 Excel 能用 openpyxl 读出表头「名称、请求方式、请求地址、入参、出参、源文件」和一行 `/api/items`。在成功用例里补上这段断言后再跑一次：

```python
    from io import BytesIO
    from openpyxl import load_workbook

    sheet = load_workbook(BytesIO(task.result_file.read())).active
    assert [cell.value for cell in sheet[1]] == ["名称", "请求方式", "请求地址", "入参", "出参", "源文件"]
    assert sheet["C2"].value == "/api/items"
```

- [ ] **Step 5: Commit**

```bash
git add apps/code_monitor/pipeline.py apps/code_monitor/tasks.py apps/code_monitor/tests/test_pipeline.py
git commit -m "feat: 编排代码扫描并在失败时不保留半份 Excel"
```

---

### Task 8: 地址和扫描接口

**Files:**
- Create: `apps/code_monitor/serializers.py`
- Create: `apps/code_monitor/views.py`
- Modify: `apps/code_monitor/urls.py`
- Modify: `apps/code_monitor/tests/test_api.py`

**Interfaces:**
- Consumes: `CodeAddress`、`ScanTask`、`run_code_monitor_scan.delay(task_id)`、`token_cache_key`
- Produces:
  - `GET/POST /api/code-monitor/addresses/`
  - `DELETE /api/code-monitor/addresses/{id}/`
  - `GET/POST /api/code-monitor/tasks/`
  - `GET /api/code-monitor/tasks/{id}/download/`
  - 创建任务的表单字段：`address_id` 与 `archive` 二选一，`model_config_id` 必填，`token` 可选且不回显

- [ ] **Step 1: Write the failing test**

把下面的测试追加到 `apps/code_monitor/tests/test_api.py`：

```python
import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.code_monitor.models import CodeAddress, ScanTask
from apps.code_monitor.tasks import token_cache_key
from apps.requirement_analysis.models import AIModelConfig
from apps.users.models import User

pytestmark = pytest.mark.django_db


def _client(username):
    user = User.objects.create_user(username=username, password="pass123456")
    client = APIClient()
    client.force_authenticate(user)
    return client, user


def _config(user, active=True):
    return AIModelConfig.objects.create(
        name=f"model-{user.username}",
        model_type="other",
        role="writer",
        base_url="https://example.com/v1",
        model_name="fake",
        created_by=user,
        is_active=active,
    )


def test_address_is_private():
    owner, owner_user = _client("owner")
    other, _other_user = _client("other")
    created = owner.post("/api/code-monitor/addresses/", {"name": "平台", "git_url": "https://example.com/a.git"}, format="json")
    assert created.status_code == 201
    assert "token" not in created.json()
    listed = other.get("/api/code-monitor/addresses/")
    assert listed.json()["count"] == 0
    assert other.delete(f"/api/code-monitor/addresses/{created.json()['id']}/").status_code == 404
    assert CodeAddress.objects.filter(created_by=owner_user).count() == 1


def test_scan_requires_active_model(monkeypatch):
    client, user = _client("need-model")
    inactive = _config(user, active=False)
    address = CodeAddress.objects.create(name="仓库", git_url="https://example.com/a.git", created_by=user)
    response = client.post("/api/code-monitor/tasks/", {
        "address_id": address.id,
        "model_config_id": inactive.id,
    }, format="multipart")
    assert response.status_code == 400


def test_token_is_cached_not_stored(monkeypatch):
    client, user = _client("token-user")
    config = _config(user)
    address = CodeAddress.objects.create(name="仓库", git_url="https://example.com/private.git", created_by=user)
    monkeypatch.setattr("apps.code_monitor.views.run_code_monitor_scan.delay", lambda task_id: None)
    response = client.post("/api/code-monitor/tasks/", {
        "address_id": address.id,
        "model_config_id": config.id,
        "token": "super-secret-token",
    }, format="multipart")
    assert response.status_code == 201
    body = response.json()
    assert "super-secret-token" not in str(body)
    task = ScanTask.objects.get(id=body["id"])
    assert task.git_url == "https://example.com/private.git"
    assert "super-secret-token" not in task.git_url
    assert task.error_message == ""
    assert cache.get(token_cache_key(task.id)) == "super-secret-token"


def test_download_only_owner_success_file(monkeypatch):
    client, user = _client("downloader")
    other, _other = _client("intruder")
    config = _config(user)
    task = ScanTask.objects.create(
        source_type=ScanTask.SOURCE_GIT,
        git_url="https://example.com/a.git",
        model_config=config,
        status=ScanTask.STATUS_SUCCEEDED,
        created_by=user,
    )
    task.result_file.save("api-extract.xlsx", __import__("django").core.files.base.ContentFile(b"excel"), save=True)
    denied = other.get(f"/api/code-monitor/tasks/{task.id}/download/")
    assert denied.status_code == 404
    allowed = client.get(f"/api/code-monitor/tasks/{task.id}/download/")
    assert allowed.status_code == 200
    assert "spreadsheetml" in allowed["Content-Type"]
```

`test_models_have_no_token_field` 保留。

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/code_monitor/tests/test_api.py -v`

Expected: FAIL，`/api/code-monitor/addresses/` 返回 404

- [ ] **Step 3: Write minimal implementation**

`apps/code_monitor/serializers.py`：

```python
from rest_framework import serializers

from apps.code_monitor.models import CodeAddress, ScanTask


class CodeAddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = CodeAddress
        fields = ["id", "name", "git_url", "created_at"]
        read_only_fields = ["id", "created_at"]


class ScanTaskSerializer(serializers.ModelSerializer):
    model_config_name = serializers.CharField(source="model_config.name", read_only=True)
    has_result = serializers.SerializerMethodField()

    class Meta:
        model = ScanTask
        fields = [
            "id", "source_type", "git_url", "model_config", "model_config_name",
            "status", "progress", "error_message", "has_result", "created_at",
        ]
        read_only_fields = fields

    def get_has_result(self, obj):
        return bool(obj.result_file)
```

`apps/code_monitor/views.py`：

```python
from django.core.cache import cache
from django.http import FileResponse
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.code_monitor.models import CodeAddress, ScanTask
from apps.code_monitor.serializers import CodeAddressSerializer, ScanTaskSerializer
from apps.code_monitor.tasks import run_code_monitor_scan, token_cache_key
from apps.requirement_analysis.models import AIModelConfig


class CodeMonitorPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 200


class CodeAddressViewSet(viewsets.ModelViewSet):
    serializer_class = CodeAddressSerializer
    pagination_class = CodeMonitorPagination
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        return CodeAddress.objects.filter(created_by=self.request.user)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class ScanTaskViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = ScanTaskSerializer
    pagination_class = CodeMonitorPagination
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        return ScanTask.objects.filter(created_by=self.request.user).select_related("model_config")

    def create(self, request, *args, **kwargs):
        address_id = request.data.get("address_id")
        archive = request.FILES.get("archive")
        if bool(address_id) == bool(archive):
            raise ValidationError("请选择一个代码地址，或上传一个 zip")
        config = AIModelConfig.objects.filter(id=request.data.get("model_config_id"), is_active=True).first()
        if config is None:
            raise ValidationError("没有已启用的模型配置")
        if address_id:
            address = self._own_address(address_id)
            task = ScanTask.objects.create(
                source_type=ScanTask.SOURCE_GIT,
                git_url=address.git_url,
                model_config=config,
                created_by=request.user,
            )
        else:
            if not archive.name.lower().endswith(".zip"):
                raise ValidationError("取代码失败: zip 打不开")
            task = ScanTask.objects.create(
                source_type=ScanTask.SOURCE_ZIP,
                archive=archive,
                model_config=config,
                created_by=request.user,
            )
        token = str(request.data.get("token") or "")
        if token:
            cache.set(token_cache_key(task.id), token, timeout=700)
        run_code_monitor_scan.delay(task.id)
        return Response(ScanTaskSerializer(task).data, status=status.HTTP_201_CREATED)

    def _own_address(self, address_id):
        address = CodeAddress.objects.filter(id=address_id, created_by=self.request.user).first()
        if address is None:
            raise ValidationError("代码地址不存在")
        return address

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        task = self.get_object()
        if task.status != ScanTask.STATUS_SUCCEEDED or not task.result_file:
            return Response({"detail": "结果文件不存在"}, status=status.HTTP_404_NOT_FOUND)
        return FileResponse(
            task.result_file.open("rb"),
            as_attachment=True,
            filename=f"api-extract-{task.id}.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
```

`apps/code_monitor/urls.py`：

```python
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.code_monitor.views import CodeAddressViewSet, ScanTaskViewSet

router = DefaultRouter()
router.register(r"addresses", CodeAddressViewSet, basename="code-monitor-address")
router.register(r"tasks", ScanTaskViewSet, basename="code-monitor-task")

urlpatterns = [
    path("", include(router.urls)),
]
```

创建 Git 任务时，`CELERY_TASK_ALWAYS_EAGER` 在测试设置里会立刻执行扫描。`test_token_is_cached_not_stored` 已经替换 `delay`，所以不会真的克隆。其他创建测试没有替换 `delay` 的，不要创建会触发克隆的成功路径；当前失败用例在 `delay` 之前就返回 400。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest apps/code_monitor/tests/test_api.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/code_monitor/serializers.py apps/code_monitor/views.py apps/code_monitor/urls.py apps/code_monitor/tests/test_api.py
git commit -m "feat: 提供代码地址和扫描任务接口"
```

---

### Task 9: 首页卡片和代码监控页面

**Files:**
- Create: `frontend/src/api/code-monitor.js`
- Create: `frontend/src/views/code-monitor/CodeMonitor.vue`
- Modify: `frontend/src/views/Home.vue`
- Modify: `frontend/src/router/index.js`
- Modify: `frontend/src/locales/lang/zh-cn/project.js`
- Modify: `frontend/src/locales/lang/en/project.js`

**Interfaces:**
- Consumes:
  - `GET/POST /api/code-monitor/addresses/`
  - `DELETE /api/code-monitor/addresses/{id}/`
  - `GET/POST /api/code-monitor/tasks/`
  - `GET /api/code-monitor/tasks/{id}/download/`
  - `GET /api/requirement-analysis/ai-models/?is_active=true`
- Produces: 首页卡片「代码监控」，以及带父栏目「提取 API」的页面

- [ ] **Step 1: Write the page and API client**

`frontend/src/api/code-monitor.js`：

```javascript
import request from '@/utils/api'

export function listAddresses(params) {
  return request({ url: '/code-monitor/addresses/', method: 'get', params })
}

export function createAddress(data) {
  return request({ url: '/code-monitor/addresses/', method: 'post', data })
}

export function deleteAddress(id) {
  return request({ url: `/code-monitor/addresses/${id}/`, method: 'delete' })
}

export function listTasks(params) {
  return request({ url: '/code-monitor/tasks/', method: 'get', params })
}

export function createTask(formData) {
  return request({
    url: '/code-monitor/tasks/',
    method: 'post',
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

export function downloadTask(id) {
  return request({
    url: `/code-monitor/tasks/${id}/download/`,
    method: 'get',
    responseType: 'blob'
  })
}

export function listActiveModels() {
  return request({
    url: '/requirement-analysis/ai-models/',
    method: 'get',
    params: { is_active: true, page_size: 200 }
  })
}
```

`frontend/src/views/code-monitor/CodeMonitor.vue`：

```vue
<template>
  <div class="code-monitor">
    <h2>代码监控</h2>
    <div class="layout">
      <el-menu :default-active="section" class="menu" @select="section = $event">
        <el-sub-menu index="extract">
          <template #title>提取 API</template>
          <el-menu-item index="addresses">代码地址</el-menu-item>
          <el-menu-item index="tasks">扫描任务</el-menu-item>
          <el-menu-item index="downloads">下载结果</el-menu-item>
        </el-sub-menu>
      </el-menu>

      <div class="panel">
        <template v-if="section === 'addresses'">
          <el-button type="primary" @click="addressDialog = true">新增地址</el-button>
          <el-table :data="addresses" style="margin-top: 12px">
            <el-table-column prop="name" label="名称" />
            <el-table-column prop="git_url" label="Git 地址" />
            <el-table-column prop="created_at" label="创建时间" />
            <el-table-column label="操作" width="100">
              <template #default="{ row }">
                <el-button link type="danger" @click="removeAddress(row.id)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </template>

        <template v-else-if="section === 'tasks'">
          <el-form label-width="100px">
            <el-form-item label="代码地址">
              <el-select v-model="form.addressId" clearable placeholder="选择已保存地址" :disabled="!!form.file" @change="form.file = null">
                <el-option v-for="item in addresses" :key="item.id" :label="item.name" :value="item.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="上传 zip">
              <input type="file" accept=".zip" :disabled="!!form.addressId" @change="onFile" />
            </el-form-item>
            <el-form-item label="访问令牌">
              <el-input v-model="form.token" type="password" show-password placeholder="私有仓库填写，不会保存" />
            </el-form-item>
            <el-form-item label="模型">
              <el-select v-model="form.modelConfigId" placeholder="选择已启用模型">
                <el-option v-for="item in models" :key="item.id" :label="item.name" :value="item.id" />
              </el-select>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :disabled="!models.length" @click="submitTask">开始扫描</el-button>
              <span v-if="!models.length" class="hint">没有已启用的模型配置</span>
            </el-form-item>
          </el-form>
          <el-table :data="tasks">
            <el-table-column prop="git_url" label="来源">
              <template #default="{ row }">{{ row.git_url || 'zip' }}</template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">{{ statusText[row.status] || row.status }}</template>
            </el-table-column>
            <el-table-column prop="progress" label="进度" width="80" />
            <el-table-column prop="error_message" label="失败原因" />
            <el-table-column prop="created_at" label="创建时间" />
          </el-table>
        </template>

        <template v-else>
          <el-table :data="downloads">
            <el-table-column prop="git_url" label="来源">
              <template #default="{ row }">{{ row.git_url || 'zip' }}</template>
            </el-table-column>
            <el-table-column prop="created_at" label="创建时间" />
            <el-table-column label="操作" width="100">
              <template #default="{ row }">
                <el-button link type="primary" @click="saveExcel(row.id)">下载</el-button>
              </template>
            </el-table-column>
          </el-table>
        </template>
      </div>
    </div>

    <el-dialog v-model="addressDialog" title="新增地址" width="480px">
      <el-form>
        <el-form-item label="名称"><el-input v-model="addressForm.name" /></el-form-item>
        <el-form-item label="Git 地址"><el-input v-model="addressForm.git_url" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addressDialog = false">取消</el-button>
        <el-button type="primary" @click="addAddress">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  createAddress, createTask, deleteAddress, downloadTask,
  listActiveModels, listAddresses, listTasks
} from '@/api/code-monitor'

const section = ref('addresses')
const addresses = ref([])
const tasks = ref([])
const models = ref([])
const addressDialog = ref(false)
const addressForm = reactive({ name: '', git_url: '' })
const form = reactive({ addressId: null, file: null, token: '', modelConfigId: null })
const statusText = { pending: '待执行', running: '执行中', succeeded: '成功', failed: '失败' }
let timer = null

const downloads = computed(() => tasks.value.filter(item => item.status === 'succeeded' && item.has_result))

function rowsOf(response) {
  const data = response.data
  if (Array.isArray(data)) return data
  return data.results || []
}

async function loadAddresses() {
  addresses.value = rowsOf(await listAddresses({ page_size: 200 }))
}

async function loadTasks() {
  tasks.value = rowsOf(await listTasks({ page_size: 200 }))
}

async function loadModels() {
  models.value = rowsOf(await listActiveModels()).filter(item => item.is_active)
}

async function addAddress() {
  await createAddress({ name: addressForm.name, git_url: addressForm.git_url })
  addressDialog.value = false
  addressForm.name = ''
  addressForm.git_url = ''
  await loadAddresses()
}

async function removeAddress(id) {
  await deleteAddress(id)
  await loadAddresses()
}

function onFile(event) {
  form.file = event.target.files[0] || null
  if (form.file) form.addressId = null
}

async function submitTask() {
  if (!form.modelConfigId) {
    ElMessage.warning('没有已启用的模型配置')
    return
  }
  if (!form.addressId && !form.file) {
    ElMessage.warning('请选择一个代码地址，或上传一个 zip')
    return
  }
  const body = new FormData()
  body.append('model_config_id', form.modelConfigId)
  if (form.addressId) body.append('address_id', form.addressId)
  if (form.file) body.append('archive', form.file)
  if (form.token) body.append('token', form.token)
  await createTask(body)
  form.token = ''
  await loadTasks()
  ElMessage.success('扫描已提交')
}

async function saveExcel(id) {
  const response = await downloadTask(id)
  const url = URL.createObjectURL(response.data)
  const link = document.createElement('a')
  link.href = url
  link.download = `api-extract-${id}.xlsx`
  link.click()
  URL.revokeObjectURL(url)
}

onMounted(async () => {
  await Promise.all([loadAddresses(), loadTasks(), loadModels()])
  timer = setInterval(() => {
    if (tasks.value.some(item => item.status === 'pending' || item.status === 'running')) {
      loadTasks()
    }
  }, 5000)
})

onUnmounted(() => clearInterval(timer))
</script>

<style scoped>
.code-monitor { padding: 16px; }
.layout { display: flex; gap: 16px; margin-top: 12px; }
.menu { width: 220px; }
.panel { flex: 1; }
.hint { margin-left: 12px; color: #909399; }
</style>
```

- [ ] **Step 2: Add the route, card, and copy**

`frontend/src/router/index.js` 在 `/home` 路由后增加：

```javascript
    {
        path: '/code-monitor',
        component: Layout,
        meta: { requiresAuth: true },
        children: [
            {
                path: '',
                name: 'CodeMonitor',
                component: () => import('@/views/code-monitor/CodeMonitor.vue')
            }
        ]
    },
```

`frontend/src/views/Home.vue` 在文档中心卡片后增加一张不进入 `hiddenHomeModules` 的卡片：

```html
        <div class="nav-card" @click="handleNavigate('code-monitor')" role="button" tabindex="0">
          <div class="card-icon code-monitor-icon">
            <el-icon><Tickets /></el-icon>
          </div>
          <h3>{{ $t('home.codeMonitor') }}</h3>
          <p>{{ $t('home.codeMonitorDesc') }}</p>
        </div>
```

`handleNavigate` 的 `routes` 增加 `'code-monitor': '/code-monitor'`。

`.card-icon` 里增加：

```scss
  &.code-monitor-icon {
    background: #f6ffed;
    color: #52c41a;
  }
```

`frontend/src/locales/lang/zh-cn/project.js` 的 `home` 卡片文案里增加：

```javascript
    codeMonitor: '代码监控',
    codeMonitorDesc: '支持从源代码中提取 API，也支持从源代码中检查代码质量',
```

`frontend/src/locales/lang/en/project.js` 同样位置增加：

```javascript
    codeMonitor: 'Code Monitoring',
    codeMonitorDesc: 'Extract APIs from source code, and check code quality from source code.',
```

- [ ] **Step 3: Build the frontend**

Run: `npm run build`

Working directory: `frontend`

Expected: 构建成功，无 Vue 编译错误

- [ ] **Step 4: Check the page in a browser**

启动后端和 `frontend` 的开发服务器。登录后确认：

- 首页有「代码监控」卡片，说明与中文文案一致。
- 点击后新标签打开 `/code-monitor`。
- 能看到父栏目「提取 API」，以及代码地址、扫描任务、下载结果。
- 页面上没有「检查代码质量」栏目。
- 新增一条代码地址后，列表只出现这一条；换一个账号看不到它。
- 没有已启用模型时，扫描提交按钮不可用。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/code-monitor.js frontend/src/views/code-monitor/CodeMonitor.vue frontend/src/views/Home.vue frontend/src/router/index.js frontend/src/locales/lang/zh-cn/project.js frontend/src/locales/lang/en/project.js
git commit -m "feat: 首页进入代码监控并提取 API"
```

---

## Spec coverage

- 首页卡片、中英文案、新标签、`/code-monitor`：Task 9
- 父栏目「提取 API」和三个子栏目：Task 9
- 检查代码质量只留在说明里：Task 9 不建栏目
- Git 地址库与 zip 上传：Task 6、Task 8、Task 9
- 令牌不落库、不进日志：Task 5、Task 7、Task 8
- 筛整棵目录：Task 1
- 60000 字符分批且不丢内容：Task 2
- 模型 JSON、去重、空入参出参：Task 3
- Excel 六列：Task 4
- 10 分钟取代码、失败不产出 Excel、删 zip 和临时目录：Task 5、Task 7
- 没有候选文件的固定原因：Task 7
- 只看自己的数据、必须有启用模型：Task 8
- Celery 与现有模型配置：Task 3、Task 7

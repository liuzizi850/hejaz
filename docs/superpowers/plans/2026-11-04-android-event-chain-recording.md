# Android 事件链录制与回放 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 APP 自动化里增加 Android 真机录制：无障碍服务记下事件链，保存为用例；回放前核对开始界面，通过后录屏并按事件链执行，最后打出 Word + mp4 + 截图压缩包。

**Architecture:** 查找、回放停止条件和报告打包是纯函数，用假设备测试。录制会话和执行分支写进 `apps/app_automation`。手机上单独一个无障碍服务，把事件发到 `127.0.0.1:27183`，由 `adb reverse` 转到 Django。手写 `ui_flow` 仍走 `AppTestExecutor`。

**Tech Stack:** Django 4.2、DRF、现有 Airtest / uiautomator、`python-docx`、adb、Android AccessibilityService、Vue 3 + Element Plus。

## Global Constraints

- 第一期只实现 Android。`platform` 为 `android`。`accessibility_id` 保留为空，不读、不写业务值。
- 平台不打开、不重启被测应用。
- 开始界面是点「录制」那一刻的全屏截图。
- 开始界面比对前裁掉屏幕顶部 8%。图像匹配使用 Airtest Template 的默认阈值。
- 查找顺序：`resource_id`，否则 `content_desc`，否则 `text` 加 `class_name`；多个结果选离 `bounds` 最近的；都没有再用 `template`。
- `input_text` 为空时该步失败，不向输入框写入。
- 任一步失败后，后续步骤记为未执行并停止。
- 开始界面不匹配：不录屏、不回放，只留当前屏和开始界面两张图，不生成含视频的结果包。
- 录屏命令失败：步骤继续，压缩包没有 mp4，Word 写明录屏失败。
- 单段录屏 180 秒，文件名为 `video-1.mp4`、`video-2.mp4`。
- Word 只写文件名，不嵌入图片或视频。
- 手机请求 `127.0.0.1:27183`。平台执行 `adb reverse tcp:27183 tcp:<Django 端口>`，本地 Django 端口按 8000。
- 同一设备已锁定时拒绝第二次录制或回放，沿用 `AppDevice.lock` / `unlock`。
- 没有 `event_chain.steps` 的用例不进入 `EventChainRunner`。

---

## File Structure

- Create: `apps/app_automation/recording/__init__.py` — 包标记
- Create: `apps/app_automation/recording/locator.py` — 控件身份选择
- Create: `apps/app_automation/recording/replay.py` — 开始界面门闩、逐步回放、失败即停
- Create: `apps/app_automation/recording/report_pack.py` — Word 与 zip
- Create: `apps/app_automation/recording/ingest.py` — 无障碍事件变成事件链步骤
- Create: `apps/app_automation/recording/dispatch.py` — `ui_flow` 与事件链分流
- Create: `apps/app_automation/recording/adb_gateway.py` — adb reverse、截图、录屏分段、无障碍开关检查
- Create: `apps/app_automation/models.py` 中的 `AppRecordingSession` — 一次录制
- Create: `apps/app_automation/views/recording_views.py` — 录制接口
- Create: `apps/app_automation/runners/event_chain_runner.py` — 把真实 adb 接到 `replay`
- Create: `recorder-android/` — 无障碍服务工程
- Create: `frontend/src/views/app-automation/recording/RecordSession.vue` — 录制页
- Modify: `apps/app_automation/models.py` — 用例和执行记录新字段
- Modify: `apps/app_automation/tasks.py` — 执行分支
- Modify: `apps/app_automation/urls.py`、`views/__init__.py`
- Modify: `frontend/src/api/app-automation.js`、`frontend/src/router/index.js`、`frontend/src/layout/index.vue`
- Test: `apps/app_automation/tests/test_event_chain_locator.py`
- Test: `apps/app_automation/tests/test_event_chain_replay.py`
- Test: `apps/app_automation/tests/test_report_pack.py`
- Test: `apps/app_automation/tests/test_event_ingest.py`
- Test: `apps/app_automation/tests/test_recording_api.py`

---

### Task 1: 控件身份查找

**Files:**
- Create: `apps/app_automation/recording/__init__.py`
- Create: `apps/app_automation/recording/locator.py`
- Test: `apps/app_automation/tests/test_event_chain_locator.py`

**Interfaces:**
- Consumes: 步骤字典，字段名与设计说明一致
- Produces: `select_by_identity(step: dict, nodes: list[dict]) -> dict | None`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/app_automation/tests/test_event_chain_locator.py -v`

Expected: FAIL with `ModuleNotFoundError` or `ImportError` for `apps.app_automation.recording.locator`

- [ ] **Step 3: Write minimal implementation**

`apps/app_automation/recording/__init__.py` 为空文件。

`apps/app_automation/recording/locator.py`：

```python
# -*- coding: utf-8 -*-


def _center(bounds):
    if not isinstance(bounds, dict):
        return None
    try:
        return (
            float(bounds["x"]) + float(bounds["w"]) / 2.0,
            float(bounds["y"]) + float(bounds["h"]) / 2.0,
        )
    except (KeyError, TypeError, ValueError):
        return None


def _distance(left, right):
    a = _center(left)
    b = _center(right)
    if a is None or b is None:
        return 0.0
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def select_by_identity(step, nodes):
    """按 resource_id、content_desc、text+class_name 的顺序选一个节点。找不到返回 None。"""
    step = step or {}
    nodes = nodes or []
    resource_id = step.get("resource_id") or ""
    content_desc = step.get("content_desc") or ""
    text = step.get("text") or ""
    class_name = step.get("class_name") or ""

    if resource_id:
        matched = [node for node in nodes if (node.get("resource_id") or "") == resource_id]
    elif content_desc:
        matched = [node for node in nodes if (node.get("content_desc") or "") == content_desc]
    elif text and class_name:
        matched = [
            node for node in nodes
            if (node.get("text") or "") == text and (node.get("class_name") or "") == class_name
        ]
    else:
        return None

    if not matched:
        return None
    if len(matched) == 1:
        return matched[0]
    return min(matched, key=lambda node: _distance(step.get("bounds"), node.get("bounds")))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest apps/app_automation/tests/test_event_chain_locator.py -v`

Expected: PASS，5 passed

- [ ] **Step 5: Commit**

```bash
git add apps/app_automation/recording/__init__.py apps/app_automation/recording/locator.py apps/app_automation/tests/test_event_chain_locator.py
git commit -m "feat: 按控件身份选择回放目标"
```

---

### Task 2: 回放门闩与失败即停

**Files:**
- Create: `apps/app_automation/recording/replay.py`
- Test: `apps/app_automation/tests/test_event_chain_replay.py`

**Interfaces:**
- Consumes: `select_by_identity(step, nodes)`
- Produces: `replay_event_chain(steps: list[dict], start_screen: str, device) -> dict`
  - 返回键：`passed`、`start_screen_mismatch`、`steps`、`current_screen`、`start_screen`、`videos`、`screenrecord_error`
  - 步骤结果键：`order`、`name`、`type`、`status`（`passed` / `failed` / `skipped`）、`screenshot`、`reason`

设备对象需要这些方法：`screenshot(name) -> str`、`match_images(expected, actual, crop_top_ratio) -> bool`、`find_nodes() -> list`、`match_template(path) -> bool`、`click(node)`、`long_press(node, duration_ms)`、`swipe(node, direction, distance)`、`input_text(node, text)`、`wait_ms(duration_ms)`、`text_exists(text) -> bool`、`selector_exists(selector) -> bool`、`start_screenrecord()`、`stop_screenrecord() -> list[str]`。`start_screenrecord` 失败时抛 `ScreenRecordError`。

- [ ] **Step 1: Write the failing test**

```python
import pytest
from apps.app_automation.recording.replay import replay_event_chain, ScreenRecordError

class FakeDevice:
    def __init__(self, match=True, nodes=None, template=False, record_ok=True):
        self.match = match
        self.nodes = nodes or []
        self.template = template
        self.record_ok = record_ok
        self.calls = []

    def screenshot(self, name):
        self.calls.append(("screenshot", name))
        return name + ".png"

    def match_images(self, expected, actual, crop_top_ratio):
        self.calls.append(("match", crop_top_ratio))
        return self.match

    def find_nodes(self):
        return self.nodes

    def match_template(self, path):
        self.calls.append(("template", path))
        return self.template

    def click(self, node):
        self.calls.append(("click", node.get("resource_id")))

    def long_press(self, node, duration_ms):
        self.calls.append(("long_press", duration_ms))

    def swipe(self, node, direction, distance):
        self.calls.append(("swipe", direction, distance))

    def input_text(self, node, text):
        self.calls.append(("input", text))

    def wait_ms(self, duration_ms):
        self.calls.append(("wait", duration_ms))

    def text_exists(self, text):
        return text == "欢迎"

    def selector_exists(self, selector):
        return False

    def start_screenrecord(self):
        if not self.record_ok:
            raise ScreenRecordError("录屏失败")
        self.calls.append(("start_record",))

    def stop_screenrecord(self):
        self.calls.append(("stop_record",))
        return ["video-1.mp4"]


def test_mismatch_does_not_record():
    device = FakeDevice(match=False)
    result = replay_event_chain([{"type": "click", "order": 1, "name": "点", "resource_id": "a"}], "start.png", device)
    assert result["start_screen_mismatch"] is True
    assert result["passed"] is False
    assert result["videos"] == []
    assert ("start_record",) not in device.calls
    assert device.calls[1] == ("match", 0.08)


def test_click_uses_identity_then_stops_on_next_failure():
    device = FakeDevice(nodes=[{"resource_id": "ok", "bounds": {"x": 0, "y": 0, "w": 0.1, "h": 0.1}}])
    steps = [
        {"type": "click", "order": 1, "name": "点确定", "resource_id": "ok", "bounds": {"x": 0, "y": 0, "w": 0.1, "h": 0.1}},
        {"type": "click", "order": 2, "name": "点缺失", "resource_id": "missing"},
        {"type": "wait", "order": 3, "name": "等待", "duration_ms": 500},
    ]
    result = replay_event_chain(steps, "start.png", device)
    assert result["passed"] is False
    assert [item["status"] for item in result["steps"]] == ["passed", "failed", "skipped"]
    assert result["steps"][2]["reason"] == "未执行"
    assert result["videos"] == ["video-1.mp4"]


def test_empty_input_fails_without_typing():
    device = FakeDevice(nodes=[{"resource_id": "pwd"}])
    result = replay_event_chain(
        [{"type": "input", "order": 1, "name": "密码", "resource_id": "pwd", "input_text": ""}],
        "start.png",
        device,
    )
    assert result["steps"][0]["status"] == "failed"
    assert ("input", "") not in device.calls


def test_template_fallback_clicks():
    device = FakeDevice(nodes=[], template=True)
    result = replay_event_chain(
        [{"type": "click", "order": 1, "name": "图标", "template": "icon.png"}],
        "start.png",
        device,
    )
    assert result["passed"] is True
    assert ("template", "icon.png") in device.calls


def test_assert_text_and_screenrecord_error_still_runs_steps():
    device = FakeDevice(record_ok=False)
    result = replay_event_chain(
        [{"type": "assert", "order": 1, "name": "欢迎语", "expected_texts": ["欢迎"], "expected_selectors": []}],
        "start.png",
        device,
    )
    assert result["screenrecord_error"] == "录屏失败"
    assert result["videos"] == []
    assert result["steps"][0]["status"] == "passed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/app_automation/tests/test_event_chain_replay.py -v`

Expected: FAIL with `ImportError` for `replay_event_chain`

- [ ] **Step 3: Write minimal implementation**

`apps/app_automation/recording/replay.py`：

```python
# -*- coding: utf-8 -*-
from .locator import select_by_identity

CROP_TOP_RATIO = 0.08


class ScreenRecordError(Exception):
    pass


def _outcome(step, status, screenshot, reason):
    return {
        "order": step.get("order"),
        "name": step.get("name") or "",
        "type": step.get("type"),
        "status": status,
        "screenshot": screenshot or "",
        "reason": reason or "",
    }


def _locate(step, device):
    node = select_by_identity(step, device.find_nodes())
    if node is not None:
        return node
    template = step.get("template") or ""
    if template and device.match_template(template):
        return {"template": template}
    return None


def _run_action(step, device):
    kind = step.get("type")
    if kind == "wait":
        device.wait_ms(int(step.get("duration_ms") or 0))
        return _outcome(step, "passed", device.screenshot("wait"), "")
    if kind == "assert":
        missing = [text for text in (step.get("expected_texts") or []) if not device.text_exists(text)]
        for selector in step.get("expected_selectors") or []:
            if _locate(selector, device) is None:
                missing.append(selector.get("resource_id") or selector.get("text") or "控件")
        shot = device.screenshot("assert")
        if missing:
            return _outcome(step, "failed", shot, "未找到: " + ", ".join(missing))
        return _outcome(step, "passed", shot, "")
    if kind == "input" and not (step.get("input_text") or ""):
        return _outcome(step, "failed", device.screenshot("input"), "输入文字为空")
    node = _locate(step, device)
    shot = device.screenshot(kind or "step")
    if node is None:
        return _outcome(step, "failed", shot, "找不到控件")
    if kind == "click":
        device.click(node)
    elif kind == "long_press":
        device.long_press(node, int(step.get("duration_ms") or 0))
    elif kind == "swipe":
        device.swipe(node, step.get("direction") or "up", float(step.get("distance") or 0))
    elif kind == "input":
        device.input_text(node, step.get("input_text") or "")
    else:
        return _outcome(step, "failed", shot, "未知步骤类型")
    return _outcome(step, "passed", shot, "")


def replay_event_chain(steps, start_screen, device):
    current = device.screenshot("current-start")
    if not device.match_images(start_screen, current, CROP_TOP_RATIO):
        return {
            "passed": False,
            "start_screen_mismatch": True,
            "steps": [],
            "current_screen": current,
            "start_screen": start_screen,
            "videos": [],
            "screenrecord_error": "",
        }
    screenrecord_error = ""
    try:
        device.start_screenrecord()
    except ScreenRecordError as exc:
        screenrecord_error = str(exc)
    outcomes = []
    failed = False
    for step in steps:
        if failed:
            outcomes.append(_outcome(step, "skipped", "", "未执行"))
            continue
        outcome = _run_action(step, device)
        outcomes.append(outcome)
        if outcome["status"] == "failed":
            failed = True
    videos = []
    if not screenrecord_error:
        videos = device.stop_screenrecord()
    return {
        "passed": not failed,
        "start_screen_mismatch": False,
        "steps": outcomes,
        "current_screen": current,
        "start_screen": start_screen,
        "videos": videos,
        "screenrecord_error": screenrecord_error,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest apps/app_automation/tests/test_event_chain_replay.py -v`

Expected: PASS，5 passed

- [ ] **Step 5: Commit**

```bash
git add apps/app_automation/recording/replay.py apps/app_automation/tests/test_event_chain_replay.py
git commit -m "feat: 事件链回放在失败和开始界面不匹配时停下"
```

---

### Task 3: Word 与结果压缩包

**Files:**
- Create: `apps/app_automation/recording/report_pack.py`
- Test: `apps/app_automation/tests/test_report_pack.py`

**Interfaces:**
- Consumes: Task 2 的步骤结果列表，以及视频文件名列表
- Produces: `write_report_docx(path: str, steps: list[dict], video_names: list[str], screenrecord_error: str) -> str` 和 `build_result_zip(zip_path: str, docx_path: str, screenshot_paths: list[str], video_paths: list[str]) -> str`

- [ ] **Step 1: Write the failing test**

```python
import os
import zipfile
from docx import Document
from apps.app_automation.recording.report_pack import write_report_docx, build_result_zip

def test_docx_lists_filenames_and_screenrecord_error(tmp_path):
    docx_path = tmp_path / "report.docx"
    write_report_docx(
        str(docx_path),
        [{"order": 1, "name": "点击登录", "type": "click", "status": "passed", "screenshot": "1.png", "reason": ""},
         {"order": 2, "name": "断言", "type": "assert", "status": "failed", "screenshot": "2.png", "reason": "未找到: 欢迎"}],
        [],
        "录屏失败",
    )
    doc = Document(str(docx_path))
    text = "\n".join(p.text for p in doc.paragraphs)
    text += "\n".join(cell.text for table in doc.tables for row in table.rows for cell in row.cells)
    assert "1.png" in text
    assert "2.png" in text
    assert "录屏失败" in text
    assert "欢迎" in text

def test_zip_contains_docx_screenshots_and_videos(tmp_path):
    shot = tmp_path / "1.png"
    shot.write_bytes(b"png")
    video = tmp_path / "video-1.mp4"
    video.write_bytes(b"mp4")
    docx_path = tmp_path / "report.docx"
    write_report_docx(str(docx_path), [], ["video-1.mp4"], "")
    zip_path = tmp_path / "result.zip"
    build_result_zip(str(zip_path), str(docx_path), [str(shot)], [str(video)])
    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
    assert "report.docx" in names
    assert "screenshots/1.png" in names
    assert "video-1.mp4" in names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/app_automation/tests/test_report_pack.py -v`

Expected: FAIL with `ImportError` for `report_pack`

- [ ] **Step 3: Write minimal implementation**

```python
# -*- coding: utf-8 -*-
import os
import zipfile
from docx import Document


def write_report_docx(path, steps, video_names, screenrecord_error):
    document = Document()
    document.add_heading("APP 事件链测试报告", level=1)
    if screenrecord_error:
        document.add_paragraph("录屏失败")
        document.add_paragraph(screenrecord_error)
    elif video_names:
        document.add_paragraph("录屏文件")
        for name in video_names:
            document.add_paragraph(os.path.basename(name))
    else:
        document.add_paragraph("录屏失败")
    table = document.add_table(rows=1, cols=6)
    headers = ("顺序", "名称", "类型", "结果", "截图文件名", "失败原因")
    for index, header in enumerate(headers):
        table.rows[0].cells[index].text = header
    for step in steps:
        row = table.add_row().cells
        row[0].text = str(step.get("order") or "")
        row[1].text = step.get("name") or ""
        row[2].text = step.get("type") or ""
        row[3].text = step.get("status") or ""
        row[4].text = os.path.basename(step.get("screenshot") or "")
        row[5].text = step.get("reason") or ""
    document.save(path)
    return path


def build_result_zip(zip_path, docx_path, screenshot_paths, video_paths):
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(docx_path, "report.docx")
        for shot in screenshot_paths:
            if shot and os.path.isfile(shot):
                archive.write(shot, "screenshots/" + os.path.basename(shot))
        for video in video_paths:
            if video and os.path.isfile(video):
                archive.write(video, os.path.basename(video))
    return zip_path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest apps/app_automation/tests/test_report_pack.py -v`

Expected: PASS，2 passed

- [ ] **Step 5: Commit**

```bash
git add apps/app_automation/recording/report_pack.py apps/app_automation/tests/test_report_pack.py
git commit -m "feat: 打包事件链 Word 报告和录屏"
```

---

### Task 4: 录制事件入库形状

**Files:**
- Create: `apps/app_automation/recording/ingest.py`
- Test: `apps/app_automation/tests/test_event_ingest.py`

**Interfaces:**
- Consumes: 手机 POST 的 JSON
- Produces: `parse_ingested_event(payload: dict, order: int, template: str) -> dict`
  - `password` 为真时 `input_text` 为空
  - `event_type` 只接受 `click`、`long_press`、`swipe`、`input`
  - 滑动的 `direction` 只接受 `up`、`down`、`left`、`right`，`distance` 夹在 0 到 1
  - 输出里 `platform` 为 `android`，`accessibility_id` 为 `""`

- [ ] **Step 1: Write the failing test**

```python
import pytest
from apps.app_automation.recording.ingest import parse_ingested_event

def test_click_event_keeps_identity_and_template():
    step = parse_ingested_event({
        "event_type": "click",
        "resource_id": "com.app:id/login",
        "content_desc": "",
        "text": "登录",
        "class_name": "Button",
        "bounds": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.1},
        "screen": {"width": 1080, "height": 2400},
        "duration_ms": 80,
    }, order=1, template="t.png")
    assert step["type"] == "click"
    assert step["platform"] == "android"
    assert step["accessibility_id"] == ""
    assert step["template"] == "t.png"
    assert step["order"] == 1
    assert step["name"] == "点击 登录"

def test_password_input_drops_text():
    step = parse_ingested_event({
        "event_type": "input",
        "text": "secret",
        "password": True,
        "resource_id": "com.app:id/pwd",
        "class_name": "EditText",
        "bounds": {"x": 0, "y": 0, "w": 1, "h": 0.05},
        "screen": {"width": 1080, "height": 1920},
    }, order=2, template="pwd.png")
    assert step["input_text"] == ""
    assert step["password"] is True

def test_swipe_distance_is_clamped():
    step = parse_ingested_event({
        "event_type": "swipe",
        "direction": "up",
        "distance": 2.4,
        "resource_id": "com.app:id/list",
        "bounds": {"x": 0, "y": 0.2, "w": 1, "h": 0.6},
        "screen": {"width": 1080, "height": 1920},
    }, order=3, template="list.png")
    assert step["distance"] == 1
    assert step["direction"] == "up"

def test_unknown_event_rejected():
    with pytest.raises(ValueError):
        parse_ingested_event({"event_type": "rotate"}, order=1, template="")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/app_automation/tests/test_event_ingest.py -v`

Expected: FAIL with `ImportError` for `parse_ingested_event`

- [ ] **Step 3: Write minimal implementation**

```python
# -*- coding: utf-8 -*-

_ALLOWED = {"click", "long_press", "swipe", "input"}
_DIRECTIONS = {"up", "down", "left", "right"}
_LABELS = {"click": "点击", "long_press": "长按", "swipe": "滑动", "input": "输入"}


def parse_ingested_event(payload, order, template):
    kind = (payload or {}).get("event_type")
    if kind not in _ALLOWED:
        raise ValueError("未知事件类型")
    password = bool(payload.get("password"))
    visible = "" if password else (payload.get("text") or "")
    direction = payload.get("direction") or "up"
    if direction not in _DIRECTIONS:
        direction = "up"
    try:
        distance = float(payload.get("distance") or 0)
    except (TypeError, ValueError):
        distance = 0
    distance = min(1.0, max(0.0, distance))
    label = visible or payload.get("content_desc") or payload.get("resource_id") or ""
    step = {
        "type": kind,
        "platform": "android",
        "accessibility_id": "",
        "order": order,
        "name": (_LABELS[kind] + " " + label).strip(),
        "resource_id": payload.get("resource_id") or "",
        "content_desc": payload.get("content_desc") or "",
        "text": visible,
        "class_name": payload.get("class_name") or "",
        "bounds": payload.get("bounds") or {},
        "template": template or "",
        "screen": payload.get("screen") or {},
        "password": password,
    }
    if kind in ("click", "long_press"):
        step["duration_ms"] = int(payload.get("duration_ms") or 0)
    if kind == "swipe":
        step["direction"] = direction
        step["distance"] = distance
    if kind == "input":
        step["input_text"] = "" if password else (payload.get("input_text") or payload.get("text") or "")
        if password:
            step["input_text"] = ""
            step["text"] = ""
    return step
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest apps/app_automation/tests/test_event_ingest.py -v`

Expected: PASS，4 passed

- [ ] **Step 5: Commit**

```bash
git add apps/app_automation/recording/ingest.py apps/app_automation/tests/test_event_ingest.py
git commit -m "feat: 把无障碍事件整理成事件链步骤"
```

---

### Task 5: 用例字段、录制会话与执行分流

**Files:**
- Modify: `apps/app_automation/models.py`
- Create: `apps/app_automation/recording/dispatch.py`
- Create: `apps/app_automation/migrations/0003_event_chain_recording.py`（由 `makemigrations` 生成，文件名以命令输出为准）
- Test: `apps/app_automation/tests/test_event_chain_dispatch.py`

**Interfaces:**
- Consumes: `AppTestCase`
- Produces: `execution_kind(test_case) -> str`，返回 `event_chain` 或 `ui_flow`
- Produces: `AppTestCase.event_chain`、`AppTestCase.start_screen`、`AppTestExecution.result_bundle_path`、`AppRecordingSession`

- [ ] **Step 1: Write the failing test**

```python
from types import SimpleNamespace
from apps.app_automation.recording.dispatch import execution_kind

def test_empty_chain_stays_on_ui_flow():
    case = SimpleNamespace(event_chain={}, ui_flow={"steps": [{"type": "click"}]})
    assert execution_kind(case) == "ui_flow"

def test_steps_select_event_chain():
    case = SimpleNamespace(event_chain={"steps": [{"type": "click"}]}, ui_flow={"steps": [{"type": "click"}]})
    assert execution_kind(case) == "event_chain"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/app_automation/tests/test_event_chain_dispatch.py -v`

Expected: FAIL with `ImportError` for `execution_kind`

- [ ] **Step 3: Write minimal implementation**

`apps/app_automation/recording/dispatch.py`：

```python
# -*- coding: utf-8 -*-

def execution_kind(test_case):
    chain = getattr(test_case, "event_chain", None) or {}
    if isinstance(chain, dict) and chain.get("steps"):
        return "event_chain"
    return "ui_flow"
```

在 `AppTestCase` 的 `ui_flow` 字段后增加：

```python
event_chain = models.JSONField(default=dict, blank=True, verbose_name='事件链')
start_screen = models.CharField(max_length=500, blank=True, default='', verbose_name='开始界面截图')
```

在 `AppTestExecution.report_path` 后增加：

```python
result_bundle_path = models.CharField(max_length=500, blank=True, default='', verbose_name='事件链结果包路径')
```

在 `AppTestExecution` 类之后新增：

```python
class AppRecordingSession(models.Model):
    """一次 Android 录制会话"""
    STATUS_CHOICES = [
        ('recording', '录制中'),
        ('interrupted', '已中断'),
        ('stopped', '已停止'),
    ]
    device = models.ForeignKey(AppDevice, on_delete=models.CASCADE, related_name='recording_sessions')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='app_recording_sessions')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='recording')
    steps = models.JSONField(default=list, blank=True)
    start_screen = models.CharField(max_length=500, blank=True, default='')
    screen = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'app_recording_sessions'
        ordering = ['-created_at']
```

然后执行：

```bash
python manage.py makemigrations app_automation --name event_chain_recording
python manage.py migrate app_automation
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest apps/app_automation/tests/test_event_chain_dispatch.py -v`

Expected: PASS，2 passed

- [ ] **Step 5: Commit**

```bash
git add apps/app_automation/models.py apps/app_automation/recording/dispatch.py apps/app_automation/migrations apps/app_automation/tests/test_event_chain_dispatch.py
git commit -m "feat: 保存事件链录制会话和结果包路径"
```

---

### Task 6: 录制接口

**Files:**
- Create: `apps/app_automation/recording/adb_gateway.py`
- Create: `apps/app_automation/views/recording_views.py`
- Modify: `apps/app_automation/views/__init__.py`
- Modify: `apps/app_automation/urls.py`
- Test: `apps/app_automation/tests/test_recording_api.py`

**Interfaces:**
- Consumes: `parse_ingested_event`、`AppRecordingSession`、`AppDevice.lock`
- Produces:
  - `POST /api/app-automation/recording-sessions/` body `{ "device_id": "<serial>" }`
  - `POST /api/app-automation/recording-sessions/<id>/events/` body 为 Task 4 的 payload
  - `POST /api/app-automation/recording-sessions/<id>/assertions/` body `{ "expected_texts": ["欢迎"], "expected_selectors": [] }`
  - `POST /api/app-automation/recording-sessions/<id>/stop/`
  - `POST /api/app-automation/recording-sessions/<id>/save/` body `{ "name": "登录", "steps": [ ... ] }`
  - `accessibility_enabled(command_output: str) -> bool`

`command_output` 来自 `adb shell settings get secure enabled_accessibility_services`。服务组件名固定为 `com.testhub.recorder/com.testhub.recorder.RecorderService`。

- [ ] **Step 1: Write the failing test**

```python
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient
from apps.app_automation.models import AppDevice, AppRecordingSession, AppTestCase
from apps.app_automation.recording.adb_gateway import accessibility_enabled

class RecordingApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="recorder", password="pw")
        self.device = AppDevice.objects.create(device_id="emulator-5554", name="emu", status="available")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_service_flag_detects_component(self):
        assert accessibility_enabled("com.testhub.recorder/com.testhub.recorder.RecorderService") is True
        assert accessibility_enabled("com.other/com.other.Service") is False

    def test_start_rejected_when_service_disabled(self):
        response = self.client.post("/api/app-automation/recording-sessions/", {"device_id": "emulator-5554"}, format="json")
        assert response.status_code == 400
        assert AppRecordingSession.objects.count() == 0

    def test_parse_ui_dump_lists_text_and_selector(self):
        from apps.app_automation.recording.adb_gateway import parse_ui_dump
        xml = '<node text="欢迎" resource-id="com.app:id/title" content-desc="" class="TextView" bounds="[0,100][100,150]" />'
        parsed = parse_ui_dump(xml, 1080, 2400)
        assert parsed["texts"] == ["欢迎"]
        assert parsed["selectors"][0]["resource_id"] == "com.app:id/title"

    def test_interrupt_keeps_steps(self):
        session = AppRecordingSession.objects.create(
            device=self.device, user=self.user, status="recording", steps=[{"type": "click", "order": 1}]
        )
        response = self.client.post(f"/api/app-automation/recording-sessions/{session.id}/interrupt/", {}, format="json")
        assert response.status_code == 200
        session.refresh_from_db()
        assert session.status == "interrupted"
        assert session.steps[0]["type"] == "click"

    def test_save_creates_case_without_touching_ui_flow(self):
        session = AppRecordingSession.objects.create(
            device=self.device,
            user=self.user,
            status="stopped",
            start_screen="start.png",
            steps=[{
                "type": "click", "platform": "android", "order": 1, "name": "点击 登录",
                "resource_id": "com.app:id/login", "template": "t.png", "input_text": "",
            }],
        )
        response = self.client.post(
            f"/api/app-automation/recording-sessions/{session.id}/save/",
            {"name": "登录用例", "steps": session.steps},
            format="json",
        )
        assert response.status_code == 201
        case = AppTestCase.objects.get(name="登录用例")
        assert case.event_chain["steps"][0]["resource_id"] == "com.app:id/login"
        assert case.start_screen == "start.png"
        assert case.ui_flow == {}
```

开始接口在测试里默认认为服务未打开。实现时读取设置 `APP_RECORDER_SERVICE_ENABLED`，测试不设置它，因此为假。真机运行时由 `adb_gateway.service_enabled(device_id)` 覆盖这个开关；单测不调用 adb。

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test apps.app_automation.tests.test_recording_api --verbosity 2`

Expected: FAIL，`accessibility_enabled` 或路由不存在

- [ ] **Step 3: Write minimal implementation**

`apps/app_automation/recording/adb_gateway.py`：

```python
# -*- coding: utf-8 -*-
SERVICE_COMPONENT = "com.testhub.recorder/com.testhub.recorder.RecorderService"
RECORDER_PORT = 27183


def accessibility_enabled(command_output):
    return SERVICE_COMPONENT in (command_output or "")


def reverse_argument(django_port=8000):
    return ["reverse", "tcp:%s" % RECORDER_PORT, "tcp:%s" % int(django_port)]


def parse_ui_dump(xml_text, screen_width, screen_height):
    import re
    texts = []
    selectors = []
    for attrs in re.findall(r"<node\s+([^>]+)/?>", xml_text or ""):
        def attr(name):
            found = re.search(name + r'="([^"]*)"', attrs)
            return found.group(1) if found else ""
        text = attr("text")
        if text:
            texts.append(text)
        bounds = attr("bounds")
        pair = re.findall(r"\d+", bounds)
        relative = {}
        if len(pair) == 4 and screen_width and screen_height:
            left, top, right, bottom = [int(item) for item in pair]
            relative = {
                "x": left / float(screen_width),
                "y": top / float(screen_height),
                "w": (right - left) / float(screen_width),
                "h": (bottom - top) / float(screen_height),
            }
        selectors.append({
            "resource_id": attr("resource-id"),
            "content_desc": attr("content-desc"),
            "text": text,
            "class_name": attr("class"),
            "bounds": relative,
        })
    return {"texts": texts, "selectors": selectors}


def read_ui_dump(device_id):
    """执行 adb shell uiautomator dump 后读回 XML。失败返回空字符串。"""
    import subprocess
    remote = "/sdcard/testhub-uidump.xml"
    dump = subprocess.run(["adb", "-s", device_id, "shell", "uiautomator", "dump", remote], capture_output=True)
    if dump.returncode != 0:
        return ""
    read = subprocess.run(["adb", "-s", device_id, "shell", "cat", remote], capture_output=True)
    if read.returncode != 0:
        return ""
    return read.stdout.decode("utf-8", errors="ignore")
```

`apps/app_automation/views/recording_views.py`：

```python
# -*- coding: utf-8 -*-
from django.conf import settings
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ..models import AppDevice, AppRecordingSession, AppTestCase
from ..recording.adb_gateway import parse_ui_dump
from ..recording.ingest import parse_ingested_event

class AppRecordingSessionViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def create(self, request):
        device_id = request.data.get("device_id")
        try:
            device = AppDevice.objects.get(device_id=device_id)
        except AppDevice.DoesNotExist:
            return Response({"message": "设备不存在"}, status=status.HTTP_404_NOT_FOUND)
        if device.status == "locked" and device.locked_by_id != request.user.id:
            return Response({"message": "设备已被其他用户锁定"}, status=status.HTTP_400_BAD_REQUEST)
        if not getattr(settings, "APP_RECORDER_SERVICE_ENABLED", False):
            return Response({"message": "请在系统设置中打开 TestHub 录制服务"}, status=status.HTTP_400_BAD_REQUEST)
        from ..recording.adb_gateway import capture_start_screen
        start_path = capture_start_screen(device.device_id)
        if device.status != "locked":
            device.lock(request.user)
        session = AppRecordingSession.objects.create(
            device=device, user=request.user, status="recording", start_screen=start_path
        )
        return Response({"id": session.id, "status": session.status}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def interrupt(self, request, pk=None):
        session = AppRecordingSession.objects.get(pk=pk, user=request.user)
        session.status = "interrupted"
        session.save(update_fields=["status", "updated_at"])
        if session.device.locked_by_id == request.user.id:
            session.device.unlock()
        return Response({"id": session.id, "steps": session.steps})

    @action(detail=True, methods=["get"], url_path="screen-tree")
    def screen_tree(self, request, pk=None):
        from ..recording.adb_gateway import read_ui_dump
        session = AppRecordingSession.objects.get(pk=pk, user=request.user)
        xml = read_ui_dump(session.device.device_id)
        width = int((session.screen or {}).get("width") or 1080)
        height = int((session.screen or {}).get("height") or 1920)
        if not xml:
            return Response({"message": "抓不到当前界面"}, status=status.HTTP_400_BAD_REQUEST)
        return Response(parse_ui_dump(xml, width, height))

    @action(detail=True, methods=["post"])
    def events(self, request, pk=None):
        session = AppRecordingSession.objects.get(pk=pk, user=request.user)
        if session.status != "recording":
            return Response({"message": "会话不在录制中"}, status=status.HTTP_400_BAD_REQUEST)
        step = parse_ingested_event(request.data, order=len(session.steps) + 1, template=request.data.get("template") or "")
        session.steps = list(session.steps) + [step]
        if step.get("screen"):
            session.screen = step["screen"]
        session.save(update_fields=["steps", "screen", "updated_at"])
        return Response(step, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def assertions(self, request, pk=None):
        session = AppRecordingSession.objects.get(pk=pk, user=request.user)
        texts = request.data.get("expected_texts") or []
        selectors = request.data.get("expected_selectors") or []
        if not texts and not selectors:
            return Response({"message": "请勾选要校验的文字或控件"}, status=status.HTTP_400_BAD_REQUEST)
        step = {
            "type": "assert",
            "platform": "android",
            "accessibility_id": "",
            "order": len(session.steps) + 1,
            "name": "断言",
            "expected_texts": texts,
            "expected_selectors": selectors,
            "template": request.data.get("template") or "",
            "screen": session.screen,
        }
        session.steps = list(session.steps) + [step]
        session.save(update_fields=["steps", "updated_at"])
        return Response(step, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def stop(self, request, pk=None):
        session = AppRecordingSession.objects.get(pk=pk, user=request.user)
        session.status = "stopped"
        session.save(update_fields=["status", "updated_at"])
        if session.device.locked_by_id == request.user.id:
            session.device.unlock()
        return Response({"id": session.id, "steps": session.steps})

    @action(detail=True, methods=["post"])
    def save(self, request, pk=None):
        session = AppRecordingSession.objects.get(pk=pk, user=request.user)
        steps = request.data.get("steps", session.steps)
        case = AppTestCase.objects.create(
            name=request.data.get("name") or "未命名录制",
            event_chain={"platform": "android", "screen": session.screen, "steps": steps},
            start_screen=session.start_screen,
            ui_flow={},
            created_by=request.user,
        )
        empty_inputs = [step for step in steps if step.get("type") == "input" and step.get("password") and not step.get("input_text")]
        return Response({"id": case.id, "empty_password_steps": [step.get("order") for step in empty_inputs]}, status=status.HTTP_201_CREATED)
```

在 `views/__init__.py` 增加导入和 `__all__` 项 `AppRecordingSessionViewSet`。

在 `urls.py` 的 router 上注册：

```python
from .views import AppRecordingSessionViewSet
router.register(r'recording-sessions', AppRecordingSessionViewSet, basename='app-recording-session')
```

录制页发现设备从列表消失时调用 `interrupt`。已收到的 `steps` 保留。`screen-tree` 在没有 dump 文本时返回 400，页面提示再试一次。开始界面截图文件由 Task 7 的 `capture_start_screen(device_id, output_path)` 写入 `session.start_screen`，调用点就在 `create` 里服务检查通过之后、`lock` 之前。测试里服务开关是关的，不会走到截图。

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test apps.app_automation.tests.test_recording_api --verbosity 2`

Expected: PASS，5 tests

- [ ] **Step 5: Commit**

```bash
git add apps/app_automation/recording/adb_gateway.py apps/app_automation/views/recording_views.py apps/app_automation/views/__init__.py apps/app_automation/urls.py apps/app_automation/tests/test_recording_api.py
git commit -m "feat: 增加 Android 录制会话接口"
```

---

### Task 7: 执行任务分流、真机回放与录屏分段

**Files:**
- Create: `apps/app_automation/runners/event_chain_runner.py`
- Modify: `apps/app_automation/tasks.py` 中 `execute_app_test_task` 与 `execute_app_suite_task` 调用执行器之前
- Test: `apps/app_automation/tests/test_screen_segments.py`

**Interfaces:**
- Consumes: `execution_kind`、`replay_event_chain`、`write_report_docx`、`build_result_zip`、`reverse_argument`
- Produces: `segment_count(elapsed_seconds: float, limit: int = 180) -> int`
- Produces: `EventChainRunner.run(execution_id: int) -> dict`，键与 `replay_event_chain` 相同，并多一个 `result_bundle_path`

分流代码放在取到 `test_case` 并锁定设备之后：

```python
from .recording.dispatch import execution_kind
if execution_kind(test_case) == "event_chain":
    from .runners.event_chain_runner import EventChainRunner
    report_result = EventChainRunner().run(execution.id)
    execution.result_bundle_path = report_result.get("result_bundle_path") or ""
    execution.total_steps = len(report_result.get("steps") or [])
    execution.passed_steps = len([step for step in report_result.get("steps") or [] if step["status"] == "passed"])
    execution.failed_steps = len([step for step in report_result.get("steps") or [] if step["status"] == "failed"])
    if report_result.get("start_screen_mismatch"):
        execution.failed_steps = 1
        execution.total_steps = max(execution.total_steps, 1)
else:
    executor = AppTestExecutor()
    report_result = executor.run_tests(...)
```

`execute_app_suite_task` 里每个用例执行前使用同一判断。没有 `event_chain.steps` 的用例仍然只构造 `AppTestExecutor`。

`segment_count`：

```python
def segment_count(elapsed_seconds, limit=180):
    if elapsed_seconds <= 0:
        return 0
    return int((elapsed_seconds + limit - 1) // limit)
```

`EventChainRunner.run` 在 `start_screen_mismatch` 为真时不调用 `build_result_zip`，把当前屏和开始界面路径写进 `execution.error_message`。匹配成功时，用 `segment_count` 决定 mp4 个数；`screenrecord_error` 非空时仍调用 `write_report_docx` 和 `build_result_zip`，视频列表为空。打包抛错时不把执行结果改成 `error`，`error_message` 写「报告未生成」。

`AdbEventDevice` 不在单元测试里连接手机。单元测试覆盖 `segment_count`。`run` 接收一个 `device` 参数，缺省时才构造 `AdbEventDevice`，这样 Task 2 的假设备仍然可以驱动同一条打包逻辑。

- [ ] **Step 1: Write the failing test**

```python
from apps.app_automation.runners.event_chain_runner import segment_count

def test_segment_count_splits_at_180_seconds():
    assert segment_count(0) == 0
    assert segment_count(1) == 1
    assert segment_count(180) == 1
    assert segment_count(181) == 2
    assert segment_count(360) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/app_automation/tests/test_screen_segments.py -v`

Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation**

`apps/app_automation/runners/event_chain_runner.py`：

```python
# -*- coding: utf-8 -*-
import os
from django.conf import settings
from apps.app_automation.recording.replay import replay_event_chain
from apps.app_automation.recording.report_pack import build_result_zip, write_report_docx

def segment_count(elapsed_seconds, limit=180):
    if elapsed_seconds <= 0:
        return 0
    return int((elapsed_seconds + limit - 1) // limit)

def video_names(elapsed_seconds, limit=180):
    return ["video-%s.mp4" % index for index in range(1, segment_count(elapsed_seconds, limit) + 1)]

class EventChainRunner:
    def run(self, execution_id, device=None):
        from apps.app_automation.models import AppTestExecution
        execution = AppTestExecution.objects.get(id=execution_id)
        case = execution.test_case
        if device is None:
            device = AdbEventDevice(execution.device.device_id, execution_id)
        result = replay_event_chain(case.event_chain.get("steps") or [], case.start_screen, device)
        if result["start_screen_mismatch"]:
            execution.error_message = "开始界面不匹配\n当前屏: %s\n开始界面: %s" % (
                result["current_screen"], result["start_screen"]
            )
            execution.result_bundle_path = ""
            execution.save(update_fields=["error_message", "result_bundle_path", "updated_at"])
            return result
        bundle_dir = os.path.join(settings.MEDIA_ROOT, "app-automation", "results", str(execution_id))
        os.makedirs(bundle_dir, exist_ok=True)
        docx_path = os.path.join(bundle_dir, "report.docx")
        try:
            write_report_docx(docx_path, result["steps"], [os.path.basename(path) for path in result["videos"]], result["screenrecord_error"])
            zip_path = os.path.join(bundle_dir, "result.zip")
            shots = [step.get("screenshot") for step in result["steps"] if step.get("screenshot")]
            build_result_zip(zip_path, docx_path, shots, result["videos"])
            result["result_bundle_path"] = zip_path
        except Exception:
            result["result_bundle_path"] = ""
            execution.error_message = "报告未生成"
            execution.save(update_fields=["error_message", "updated_at"])
            return result
        execution.result_bundle_path = result["result_bundle_path"]
        execution.save(update_fields=["result_bundle_path", "updated_at"])
        return result
```

`capture_start_screen` 放在 `adb_gateway.py`，供录制接口调用。`AdbEventDevice` 放在 `event_chain_runner.py`。

```python
import subprocess
import threading
import time
import cv2
from airtest.core.cv import Template
from apps.app_automation.recording.replay import ScreenRecordError

class AdbEventDevice:
    def __init__(self, device_id, execution_id):
        self.device_id = device_id
        self.execution_id = execution_id
        self._videos = []
        self._stop = False

    def _dir(self):
        directory = os.path.join(settings.MEDIA_ROOT, "app-automation", "results", str(self.execution_id))
        os.makedirs(directory, exist_ok=True)
        return directory

    def screenshot(self, name):
        path = os.path.join(self._dir(), "%s.png" % name)
        data = subprocess.check_output(["adb", "-s", self.device_id, "exec-out", "screencap", "-p"])
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def match_images(self, expected, actual, crop_top_ratio):
        left = cv2.imread(expected)
        right = cv2.imread(actual)
        top = int(left.shape[0] * crop_top_ratio)
        left = left[top:, :, :]
        right = right[top:, :, :]
        return Template(left).match_in(right) is not None

    def start_screenrecord(self):
        self._stop = False
        self._thread = threading.Thread(target=self._record_loop, daemon=True)
        self._thread.start()
        time.sleep(0.5)
        if not self._videos and getattr(self, "_record_error", ""):
            raise ScreenRecordError("录屏失败")

    def _record_loop(self):
        index = 1
        while not self._stop:
            remote = "/sdcard/testhub-video-%s.mp4" % index
            try:
                proc = subprocess.Popen(["adb", "-s", self.device_id, "shell", "screenrecord", "--time-limit", "180", remote])
            except OSError:
                self._record_error = "录屏失败"
                return
            while proc.poll() is None and not self._stop:
                time.sleep(0.5)
            if proc.poll() is None:
                subprocess.call(["adb", "-s", self.device_id, "shell", "pkill", "-l", "2", "screenrecord"])
                proc.wait(timeout=8)
            local = os.path.join(self._dir(), "video-%s.mp4" % index)
            pulled = subprocess.call(["adb", "-s", self.device_id, "pull", remote, local])
            if pulled != 0:
                self._record_error = "录屏失败"
                return
            self._videos.append(local)
            index += 1

    def stop_screenrecord(self):
        self._stop = True
        self._thread.join(timeout=15)
        return list(self._videos)

def capture_start_screen(device_id):
    directory = os.path.join(settings.MEDIA_ROOT, "app-automation", "recordings", "starts")
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "%s.png" % device_id)
    data = subprocess.check_output(["adb", "-s", device_id, "exec-out", "screencap", "-p"])
    with open(path, "wb") as handle:
        handle.write(data)
    return path
```

`find_nodes` 调用 `read_ui_dump` 再 `parse_ui_dump`，返回 `selectors`。`match_template` 用 Airtest `Template(template_path).match_in` 当前屏。`click`、`long_press`、`swipe`、`input_text` 用 `adb shell input`。`text_exists` 在 `find_nodes()` 的 `text` 里查找。`start_screenrecord` 立刻返回，录屏线程每满 180 秒拉回一段并开始 `video-2.mp4`。`stop_screenrecord` 通知线程停掉当前段并返回已经拉回的文件。

`tasks.py` 的 `execute_app_test_task` 与 `execute_app_suite_task` 在锁定设备之后按 `execution_kind` 分支。事件链分支调用 `EventChainRunner().run(execution.id)`，不调用 `AppTestExecutor`，也不调用 `_generate_allure_report`。

`recording_views.create` 在服务检查通过后调用 `capture_start_screen`，把返回路径存进 `session.start_screen`。

- [ ] **Step 4: Run tests**

Run: `pytest apps/app_automation/tests/test_event_chain_locator.py apps/app_automation/tests/test_event_chain_replay.py apps/app_automation/tests/test_report_pack.py apps/app_automation/tests/test_event_ingest.py apps/app_automation/tests/test_event_chain_dispatch.py apps/app_automation/tests/test_screen_segments.py -v`

Expected: PASS

Run: `python manage.py test apps.app_automation.tests.test_recording_api --verbosity 2`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/app_automation/runners/event_chain_runner.py apps/app_automation/tasks.py apps/app_automation/tests/test_screen_segments.py
git commit -m "feat: 事件链用例回放并保留录屏结果包"
```

---

### Task 8: Android 录制服务

**Files:**
- Create: `recorder-android/settings.gradle`
- Create: `recorder-android/build.gradle`
- Create: `recorder-android/app/build.gradle`
- Create: `recorder-android/app/src/main/AndroidManifest.xml`
- Create: `recorder-android/app/src/main/java/com/testhub/recorder/RecorderService.java`
- Create: `recorder-android/app/src/main/res/xml/accessibility_service_config.xml`

**Interfaces:**
- Consumes: `POST http://127.0.0.1:27183/api/app-automation/recording-sessions/<id>/events/`
- Produces: Task 4 的 JSON。组件名 `com.testhub.recorder/com.testhub.recorder.RecorderService`

平台在 `APP_RECORDER_SERVICE_ENABLED` 检查通过后执行：

```text
adb -s <serial> reverse tcp:27183 tcp:8000
adb -s <serial> shell am broadcast -a com.testhub.recorder.START --es ingestUrl http://127.0.0.1:27183/api/app-automation/recording-sessions/<id>/events/
```

停止时广播 `com.testhub.recorder.STOP`。

服务行为：

- `TYPE_VIEW_CLICKED` 记为 `click`
- `TYPE_VIEW_LONG_CLICKED` 记为 `long_press`
- `TYPE_VIEW_SCROLLED` 记为 `swipe`，`fromIndex > toIndex` 为 `up`，否则 `down`；`distance` 用滚动差值除以 `itemCount`，再夹到 0 到 1
- `TYPE_VIEW_TEXT_CHANGED` 记为 `input`；`isPassword` 为真时 `password` 为 true 且 `text` 为空
- `bounds` 用节点在屏幕上的位置除以屏幕宽高，得到 0 到 1
- 广播到达前不发送事件

验收命令（装到一台已开 USB 调试的手机后）：

```text
adb install -r recorder-android/app/build/outputs/apk/debug/app-debug.apk
adb shell settings get secure enabled_accessibility_services
```

未手动打开服务时，输出里没有 `com.testhub.recorder/com.testhub.recorder.RecorderService`。打开后再查，输出包含该组件。

- [ ] **Step 1: 写服务配置和事件投递**

`accessibility_service_config.xml` 监听 `typeViewClicked|typeViewLongClicked|typeViewScrolled|typeViewTextChanged`，`canRetrieveWindowContent` 为 true。

`RecorderService.onAccessibilityEvent` 读取 `AccessibilityNodeInfo` 的 `viewIdResourceName`、`contentDescription`、`text`、`className`、`getBoundsInScreen`、`isPassword`，按上面的映射 POST JSON。HTTP 使用 `HttpURLConnection`，失败只记 log，不抛到系统。

- [ ] **Step 2: 编译**

Run: `cd recorder-android; .\gradlew.bat assembleDebug`

Expected: `BUILD SUCCESSFUL`，产出 `app-debug.apk`

- [ ] **Step 3: Commit**

```bash
git add recorder-android
git commit -m "feat: 增加 Android 无障碍录制服务"
```

---

### Task 9: 录制页

**Files:**
- Create: `frontend/src/views/app-automation/recording/RecordSession.vue`
- Modify: `frontend/src/api/app-automation.js`
- Modify: `frontend/src/router/index.js` 在 `test-cases` 路由后
- Modify: `frontend/src/layout/index.vue` 在用例菜单旁

**Interfaces:**
- Consumes: Task 6 的五个接口，以及现有 `getAppDevices`
- Produces: 路由 `/app-automation/recording`，名称 `AppRecordingSession`

页面顺序：选择 `device_id`，点「录制」。400 时展示返回的 `message`（服务未打开或设备已锁定）。成功后显示步骤表，列为顺序、名称、类型。点「标为断言」弹出当前步骤之外的输入框，提交 `expected_texts`。点「停止」后可以删除一行、上移下移，并追加一行 `{ "type": "wait", "duration_ms": 1000, "name": "等待", "platform": "android", "order": <新序号> }`。保存时把调整后的 `steps` 和用例名 POST 到 `save`。若响应里 `empty_password_steps` 非空，提示这些步骤的密码要补上，并允许在表格里编辑对应行的 `input_text` 后再次保存。

执行详情沿用执行列表。`result_bundle_path` 非空时显示下载链接，地址为该路径对应的媒体 URL。

- [ ] **Step 1: 接上 API 与路由**

在 `app-automation.js` 增加 `createRecordingSession`、`postRecordingEvent`、`postRecordingAssertion`、`stopRecordingSession`、`saveRecordingSession`，URL 与 Task 6 一致。

路由：

```javascript
{
    path: 'recording',
    name: 'AppRecordingSession',
    component: () => import('@/views/app-automation/recording/RecordSession.vue')
}
```

菜单项 `index="/app-automation/recording"`，标题用「录制用例」。`titleMap` 增加同一路径。

- [ ] **Step 2: 写录制页**

使用 Element Plus 的 `el-select`、`el-table`、`el-button`、`el-dialog`。不在这个页面启动回放。保存成功后跳到 `/app-automation/test-cases`。

- [ ] **Step 3: Lint**

Run: `npm run lint -- src/views/app-automation/recording/RecordSession.vue src/api/app-automation.js src/router/index.js src/layout/index.vue`

在 `frontend` 目录执行。

Expected: 这两个改动的文件没有新增 error

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/app-automation/recording/RecordSession.vue frontend/src/api/app-automation.js frontend/src/router/index.js frontend/src/layout/index.vue
git commit -m "feat: 增加 APP 事件链录制页"
```

---

## Spec coverage

- 录制点击、滑动、输入：Task 4、Task 6、Task 8
- 等待由人在停止后补上：Task 9
- 断言在电脑上勾选：Task 6 `assertions`、Task 9
- 开始界面来自点录制那一刻：Task 7 的 `capture_start_screen`，由 Task 6 的 `create` 在服务检查通过后调用并写入 `session.start_screen`
- 断言抓当前界面：Task 6 的 `parse_ui_dump` 与 `screen-tree`
- 录制中断保留步骤：Task 6 的 `interrupt`
- 回放门闩、失败即停、空密码、录屏失败仍继续：Task 2
- Word、zip、180 秒分段、不嵌视频：Task 3、Task 7
- `ui_flow` 不改道：Task 5、Task 7
- 服务未打开不建会话、设备锁定：Task 6
- 真机整条链路：Task 8 安装服务后，按设计说明「真机」五步手工验收

## 手工验收

服务安装并在系统设置打开后，按设计说明里的五步走一遍：未开服务被拒绝、录制并保存、错误界面拒绝启动、正确界面产出压缩包、错误断言失败但仍有结果包。

import json
import zipfile

import pytest
from django.core.files.base import ContentFile

from apps.code_monitor.acquire import AcquireError
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

    from io import BytesIO
    from openpyxl import load_workbook

    sheet = load_workbook(BytesIO(task.result_file.read())).active
    assert [cell.value for cell in sheet[1]] == ["名称", "请求方式", "请求地址", "入参", "出参", "源文件"]
    assert sheet["C2"].value == "/api/items"


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


def _zip_scan_task(filename):
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
    task.archive.save(filename, ContentFile(buffer.getvalue()), save=True)
    return task


def test_unzip_timeout_fails_without_excel(monkeypatch):
    import subprocess

    task = _zip_scan_task("hang.zip")
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["timeout"] = kwargs.get("timeout")
        seen["cmd"] = cmd
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))

    monkeypatch.setattr("apps.code_monitor.pipeline.FETCH_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr("apps.code_monitor.pipeline.subprocess.run", fake_run)
    execute_scan(task.id, token="super-secret-token")
    task.refresh_from_db()
    assert seen["timeout"] == 0.2
    assert "super-secret-token" not in " ".join(str(part) for part in seen["cmd"])
    assert task.status == ScanTask.STATUS_FAILED
    assert task.error_message == "克隆或解压超时"
    assert "super-secret-token" not in task.error_message
    assert not task.result_file


def test_failure_redacts_token_and_ignores_cause_stderr(monkeypatch):
    user = _user()
    config = _config(user)
    task = ScanTask.objects.create(
        source_type=ScanTask.SOURCE_GIT,
        git_url="https://example.com/repo.git",
        model_config=config,
        created_by=user,
    )

    def fake_clone(url, dest, token="", timeout=600):
        cause = OSError("stderr super-secret-token")
        raise AcquireError("取代码失败: super-secret-token") from cause

    monkeypatch.setattr("apps.code_monitor.pipeline.clone_repository", fake_clone)
    execute_scan(task.id, token="super-secret-token")
    task.refresh_from_db()
    assert task.status == ScanTask.STATUS_FAILED
    assert task.error_message == "取代码失败: ***"
    assert "stderr" not in task.error_message
    assert "super-secret-token" not in task.error_message
    assert not task.result_file


def test_bad_zip_message_has_no_traceback():
    user = _user()
    config = _config(user)
    task = ScanTask.objects.create(
        source_type=ScanTask.SOURCE_ZIP,
        model_config=config,
        created_by=user,
    )
    task.archive.save("nope.zip", ContentFile(b"not a zip"), save=True)
    execute_scan(task.id, token="super-secret-token")
    task.refresh_from_db()
    assert task.status == ScanTask.STATUS_FAILED
    assert task.error_message == "取代码失败: zip 打不开"
    assert "Traceback" not in task.error_message
    assert "super-secret-token" not in task.error_message
    assert not task.result_file


def test_git_clone_target_is_temp_root(monkeypatch):
    user = _user()
    config = _config(user)
    task = ScanTask.objects.create(
        source_type=ScanTask.SOURCE_GIT,
        git_url="https://example.com/repo.git",
        model_config=config,
        created_by=user,
    )
    seen = {}

    def fake_clone(url, dest, token="", timeout=600):
        seen["url"] = url
        seen["dest"] = dest
        seen["token"] = token
        dest = __import__("pathlib").Path(dest)
        (dest / "src").mkdir(parents=True)
        (dest / "src" / "api.js").write_text("axios.get('/api/items')", encoding="utf-8")

    def fake_call(model_config, chunks):
        seen["source_file"] = chunks[0].source_file
        return json.dumps([{
            "name": "列表",
            "method": "GET",
            "url": "/api/items",
            "request_params": "",
            "response_params": "",
            "source_file": chunks[0].source_file,
        }])

    monkeypatch.setattr("apps.code_monitor.pipeline.clone_repository", fake_clone)
    monkeypatch.setattr("apps.code_monitor.extract.call_model", fake_call)
    execute_scan(task.id, token="super-secret-token")
    task.refresh_from_db()
    assert seen["url"] == "https://example.com/repo.git"
    assert seen["token"] == "super-secret-token"
    assert seen["dest"].name.startswith("code_monitor_")
    assert seen["source_file"] == "src/api.js"
    assert task.status == ScanTask.STATUS_SUCCEEDED
    assert "super-secret-token" not in task.error_message


def test_celery_task_reads_token_from_cache_then_deletes_it(monkeypatch):
    from django.core.cache import cache

    from apps.code_monitor.tasks import run_code_monitor_scan, token_cache_key

    user = _user()
    config = _config(user)
    task = ScanTask.objects.create(
        source_type=ScanTask.SOURCE_GIT,
        git_url="https://example.com/repo.git",
        model_config=config,
        created_by=user,
    )
    seen = {}

    def fake_execute(task_id, token=""):
        seen["task_id"] = task_id
        seen["token"] = token
        seen["cached_during_scan"] = cache.get(token_cache_key(task_id))

    monkeypatch.setattr("apps.code_monitor.tasks.execute_scan", fake_execute)
    cache.set(token_cache_key(task.id), "super-secret-token", timeout=700)
    outcome = run_code_monitor_scan.apply(args=[task.id])
    assert outcome.successful()
    assert seen["task_id"] == task.id
    assert seen["token"] == "super-secret-token"
    assert seen["cached_during_scan"] is None
    assert cache.get(token_cache_key(task.id)) is None
    task.refresh_from_db()
    assert task.celery_task_id
    assert run_code_monitor_scan.run.__code__.co_varnames[:2] == ("self", "task_id")

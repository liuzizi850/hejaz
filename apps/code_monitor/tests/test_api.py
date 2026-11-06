from pathlib import Path

import ast

import pytest
from django.core.cache import caches
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


def _caches_from_settings(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "CACHES":
                    return node.value
    return None


def _dict_fields(node):
    fields = {}
    for key, value in zip(node.keys, node.values):
        if not isinstance(key, ast.Constant):
            continue
        if isinstance(value, ast.Constant):
            fields[key.value] = value.value
        elif isinstance(value, ast.Name):
            fields[key.value] = value.id
    return fields


def test_production_settings_use_redis_cache():
    settings_path = Path(__file__).resolve().parents[3] / "backend" / "settings.py"
    caches_node = _caches_from_settings(settings_path)
    assert isinstance(caches_node, ast.Dict)
    aliases = {}
    for key, value in zip(caches_node.keys, caches_node.values):
        if isinstance(key, ast.Constant):
            aliases[key.value] = value
    code_monitor = _dict_fields(aliases["code_monitor"])
    assert code_monitor["BACKEND"] == "django.core.cache.backends.redis.RedisCache"
    assert code_monitor["LOCATION"] == "REDIS_URL"
    default = _dict_fields(aliases["default"])
    assert default["BACKEND"] == "django.core.cache.backends.locmem.LocMemCache"


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
    assert caches["code_monitor"].get(token_cache_key(task.id)) == "super-secret-token"
    assert "token" not in {field.name for field in task._meta.fields}


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


def test_address_rejects_unsafe_git_url():
    client, user = _client("unsafe-address")
    for url in ("file:///tmp/repo.git", "ssh://git@example.com/a.git", "/tmp/repo.git", "ext::sh", "--upload-pack=evil"):
        response = client.post("/api/code-monitor/addresses/", {"name": "x", "git_url": url}, format="json")
        assert response.status_code == 400
        assert response.json()["git_url"]
    assert CodeAddress.objects.filter(created_by=user).count() == 0


def test_git_task_rejects_unsafe_address_url(monkeypatch):
    client, user = _client("unsafe-task")
    config = _config(user)
    address = CodeAddress.objects.create(name="bad", git_url="file:///tmp/repo.git", created_by=user)
    called = {"n": 0}

    def delay(task_id):
        called["n"] += 1

    monkeypatch.setattr("apps.code_monitor.views.run_code_monitor_scan.delay", delay)
    response = client.post("/api/code-monitor/tasks/", {
        "address_id": address.id,
        "model_config_id": config.id,
        "token": "super-secret-token",
    }, format="multipart")
    assert response.status_code == 400
    assert called["n"] == 0
    assert ScanTask.objects.filter(created_by=user).count() == 0
    assert "super-secret-token" not in str(response.content)


def test_enqueue_failure_marks_task_failed_and_drops_token_and_zip(monkeypatch):
    client, user = _client("enqueue-fail")
    config = _config(user)

    def explode(task_id):
        raise RuntimeError("broker down")

    monkeypatch.setattr("apps.code_monitor.views.run_code_monitor_scan.delay", explode)
    archive = SimpleUploadedFile("repo.zip", b"not-a-real-zip", content_type="application/zip")
    response = client.post("/api/code-monitor/tasks/", {
        "archive": archive,
        "model_config_id": config.id,
        "token": "super-secret-token",
    }, format="multipart")
    assert response.status_code == 400
    assert response.json()["detail"] == "提交扫描失败"
    assert "super-secret-token" not in str(response.content)
    task = ScanTask.objects.get(created_by=user)
    assert task.status == ScanTask.STATUS_FAILED
    assert task.error_message == "提交扫描失败"
    assert "super-secret-token" not in task.error_message
    assert "token" not in {field.name for field in task._meta.fields}
    assert not task.archive
    assert caches["code_monitor"].get(token_cache_key(task.id)) is None

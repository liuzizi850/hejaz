# -*- coding: utf-8 -*-
"""API tests for REQ-002 execution-and-report endpoints."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.app_automation.ai_run.constants import (
    DEVICE_OFFLINE,
    INVALID_FEATURE,
    INVALID_SHARE,
    INVALID_UPLOAD,
    LLM_NOT_CONFIGURED,
    NO_CONNECTED_DEVICES,
    WORKER_NOT_READY,
)
from apps.app_automation.ai_run.models import AiRunExecution, AiRunShare
from apps.app_automation.ai_run.storage import run_output_dir
from apps.users.models import User
from tools.req001.adb_utils import AdbDevice
from tools.req001.html_report import CaseResult, RunReport, write_report
from tools.req001.run_selected import RunSelectedResult

pytestmark = pytest.mark.django_db

BASE = "/api/app-automation/ai-runs"


def _user(username="tester"):
    return User.objects.create_user(username=username, password="pass123456")


def _auth(user=None):
    user = user or _user()
    client = APIClient()
    client.force_authenticate(user)
    return client, user


def _anon():
    return APIClient()


def _assert_safe(payload):
    text = str(payload)
    assert "DASHSCOPE" not in text
    assert "OPENAI_API_KEY" not in text
    assert ".commit-review.env" not in text
    assert "C:\\Project" not in text
    assert "C:/Project" not in text
    assert "ensure_emulator" not in text
    assert "run_mvp.py" not in text
    assert "sk-" not in text.lower()



def _body(response):
    if hasattr(response, 'streaming_content'):
        return b''.join(response.streaming_content).decode('utf-8', 'replace')
    return response.content.decode('utf-8', 'replace')

VALID_FEATURE = (
    "# language: zh-CN\n"
    "功能: 上传脚本\n"
    "  场景: 打开应用\n"
    "    假如 已安装应用\n"
    "    当 启动应用\n"
    "    那么 应用在前台\n"
)


@pytest.fixture
def no_devices(monkeypatch):
    monkeypatch.setattr(
        "apps.app_automation.ai_run.devices.list_connected_android_devices",
        lambda **kwargs: {"devices": [], "message": NO_CONNECTED_DEVICES},
    )
    monkeypatch.setattr("apps.app_automation.ai_run.execution.serial_is_online", lambda *a, **k: False)


@pytest.fixture
def online_device(monkeypatch):
    serial = "emulator-5554"
    payload = {"devices": [{"serial": serial, "status": "online", "name": "模拟器 emulator-5554"}], "message": ""}
    monkeypatch.setattr(
        "apps.app_automation.ai_run.devices.list_connected_android_devices",
        lambda **kwargs: payload,
    )
    monkeypatch.setattr("apps.app_automation.ai_run.execution.serial_is_online", lambda value, **k: value == serial)
    monkeypatch.setattr("apps.app_automation.ai_run.devices.serial_is_online", lambda value, **k: value == serial)
    return serial


@pytest.fixture
def workers_ready(monkeypatch):
    monkeypatch.setattr("apps.app_automation.ai_run.execution.celery_workers_ready", lambda **k: True)


@pytest.fixture
def workers_down(monkeypatch):
    monkeypatch.setattr("apps.app_automation.ai_run.execution.celery_workers_ready", lambda **k: False)


def test_unauthenticated_requests_are_rejected(no_devices):
    client = _anon()
    assert client.get(f"{BASE}/scripts/").status_code in (401, 403)
    assert client.post(f"{BASE}/scripts/upload/", {}, format="multipart").status_code in (401, 403)
    assert client.get(f"{BASE}/devices/").status_code in (401, 403)
    assert client.post(f"{BASE}/runs/", {"serial": "x", "script_ids": ["builtin:x"]}, format="json").status_code in (401, 403)
    assert client.get(f"{BASE}/runs/1/").status_code in (401, 403)
    assert client.get(f"{BASE}/runs/1/download/").status_code in (401, 403)
    assert client.post(f"{BASE}/runs/1/share/").status_code in (401, 403)


def test_list_builtin_scripts_hides_absolute_paths():
    client, _user_obj = _auth()
    response = client.get(f"{BASE}/scripts/")
    assert response.status_code == 200
    body = response.json()
    _assert_safe(body)
    scripts = body["scripts"]
    ids = {item["id"] for item in scripts}
    names = " ".join(item.get("name", "") for item in scripts)
    assert any(i.startswith("builtin:REQ-001-S1") for i in ids)
    assert any(i.startswith("builtin:REQ-001-S2") for i in ids)
    assert any(i.startswith("builtin:REQ-001-S3") for i in ids)
    for item in scripts:
        assert "C:\\" not in item["id"]
        assert "/" not in item["id"].replace("builtin:", "").replace("upload:", "")
        assert "fixtures" not in item["id"]


def test_upload_valid_feature_and_reject_illegal():
    client, _user_obj = _auth()
    ok = client.post(
        f"{BASE}/scripts/upload/",
        {"file": SimpleUploadedFile("demo.feature", VALID_FEATURE.encode("utf-8"), content_type="text/plain")},
        format="multipart",
    )
    assert ok.status_code == 201
    body = ok.json()
    _assert_safe(body)
    assert body["script"]["id"].startswith("upload:")
    assert body["script"]["source"] == "upload"

    bad = client.post(
        f"{BASE}/scripts/upload/",
        {"file": SimpleUploadedFile("demo.feature", b"this is not gherkin at all", content_type="text/plain")},
        format="multipart",
    )
    assert bad.status_code == 400
    assert bad.json()["message"]
    _assert_safe(bad.json())

    wrong_ext = client.post(
        f"{BASE}/scripts/upload/",
        {"file": SimpleUploadedFile("notes.txt", b"Feature: x\n", content_type="text/plain")},
        format="multipart",
    )
    assert wrong_ext.status_code == 400
    _assert_safe(wrong_ext.json())


def test_device_list_filters_offline_and_empty_message(monkeypatch):
    from apps.app_automation.ai_run.devices import list_connected_android_devices

    def mixed():
        return [
            AdbDevice(serial="emulator-5554", state="device"),
            AdbDevice(serial="emulator-5556", state="offline"),
            AdbDevice(serial="ABCD1234", state="unauthorized"),
        ]

    filtered = list_connected_android_devices(list_devices_fn=mixed)
    assert [d["serial"] for d in filtered["devices"]] == ["emulator-5554"]
    assert not filtered["message"]

    empty_direct = list_connected_android_devices(list_devices_fn=lambda: [])
    assert empty_direct["devices"] == []
    assert NO_CONNECTED_DEVICES in empty_direct["message"]

    client, _user_obj = _auth()
    monkeypatch.setattr(
        "apps.app_automation.ai_run.views.list_connected_android_devices",
        lambda **k: filtered,
    )
    response = client.get(f"{BASE}/devices/")
    assert response.status_code == 200
    body = response.json()
    _assert_safe(body)
    serials = [d["serial"] for d in body["devices"]]
    assert serials == ["emulator-5554"]
    assert "scrcpy" not in str(body).lower()
    assert "ensure_emulator" not in str(body)
    assert "启动模拟器" not in str(body)

    monkeypatch.setattr(
        "apps.app_automation.ai_run.views.list_connected_android_devices",
        lambda **k: empty_direct,
    )
    empty = client.get(f"{BASE}/devices/")
    assert empty.status_code == 200
    assert empty.json()["devices"] == []
    assert NO_CONNECTED_DEVICES in empty.json()["message"]
    _assert_safe(empty.json())


def test_create_run_rejected_when_worker_down(online_device, workers_down):
    client, _user_obj = _auth()
    response = client.post(
        f"{BASE}/runs/",
        {"serial": online_device, "script_ids": ["builtin:REQ-001-S1_open_app"]},
        format="json",
    )
    assert response.status_code == 503
    assert response.json()["message"] == WORKER_NOT_READY
    assert AiRunExecution.objects.count() == 0
    _assert_safe(response.json())


def test_create_run_rejected_when_device_offline(workers_ready, no_devices):
    client, _user_obj = _auth()
    response = client.post(
        f"{BASE}/runs/",
        {"serial": "emulator-5554", "script_ids": ["builtin:REQ-001-S1_open_app"]},
        format="json",
    )
    assert response.status_code == 400
    assert response.json()["message"] == DEVICE_OFFLINE
    _assert_safe(response.json())


def test_create_run_dispatches_and_completes_with_s3_failure(online_device, workers_ready, monkeypatch, tmp_path):
    client, user = _auth()

    def fake_adapter(serial, paths, output_dir):
        assert serial == online_device
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        shot = output_dir / "work.png"
        shot.write_bytes(b"\x89PNG\r\n\x1a\n" + b"2" * 16)
        cases = [
            CaseResult("REQ-001-S1", "打开应用", "pass", screenshots=[str(shot)]),
            CaseResult("REQ-001-S2", "1+1=2", "pass", screenshots=[str(shot)]),
            CaseResult("REQ-001-S3", "1+1=3", "fail", failure_reason="断言失败：期望 3", screenshots=[str(shot)]),
        ]
        report = RunReport(
            run_id="test",
            device_serial=serial,
            app_package="com.example",
            app_source="preinstalled_calculator",
            cases=cases,
        )
        index = write_report(report, output_dir)
        public = []
        for case in cases:
            rels = list((output_dir / "screenshots").rglob("*.png")) if (output_dir / "screenshots").exists() else []
            public.append(
                CaseResult(
                    case.case_id,
                    case.name,
                    case.status,
                    case.failure_reason,
                    screenshots=[p.relative_to(output_dir).as_posix() for p in rels if case.case_id in p.as_posix()]
                    or [p.relative_to(output_dir).as_posix() for p in rels[:1]],
                )
            )
        return RunSelectedResult(
            ok=True,
            message="",
            report_dir=output_dir,
            report_index=index,
            run_id="test",
            device_serial=serial,
            app_package="com.example",
            cases=public,
        )

    monkeypatch.setattr("apps.app_automation.ai_run.execution._call_adapter", fake_adapter)
    # Always-eager celery will run the real task, which calls execute_run -> _call_adapter
    response = client.post(
        f"{BASE}/runs/",
        {
            "serial": online_device,
            "script_ids": [
                "builtin:REQ-001-S1_open_app",
                "builtin:REQ-001-S2_add_one_plus_one",
                "builtin:REQ-001-S3_wrong_assertion",
            ],
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    body = response.json()
    _assert_safe(body)
    run_id = body["run"]["id"]
    detail = client.get(f"{BASE}/runs/{run_id}/")
    assert detail.status_code == 200
    run = detail.json()["run"]
    _assert_safe(run)
    assert run["status"] == "completed"
    assert run["result"] == "failed"
    cases = {c["id"]: c for c in run["cases"]}
    assert cases["REQ-001-S3"]["status"] == "fail"
    assert cases["REQ-001-S3"]["failure_reason"]
    assert cases["REQ-001-S3"]["screenshots"]
    assert cases["REQ-001-S1"]["status"] == "pass"

    html = client.get(run["report_html_url"])
    assert html.status_code == 200
    content = _body(html)
    assert "REQ-001-S3" in content
    _assert_safe(content)

    download = client.get(f"{BASE}/runs/{run_id}/download/")
    assert download.status_code == 200
    zf = ZipFile(BytesIO(download.content))
    names = zf.namelist()
    assert "index.html" in names
    assert any(n.startswith("screenshots/") for n in names)
    assert all(not n.startswith("/") and ":" not in n and ".." not in n for n in names)
    # zip must be openable offline
    html_in_zip = zf.read("index.html").decode("utf-8")
    assert "REQ-001-S3" in html_in_zip

    share = client.post(f"{BASE}/runs/{run_id}/share/")
    assert share.status_code == 201
    token = share.json()["share"]["token"]
    url = share.json()["share"]["url"]
    assert token not in ("", "1", "2", "abc")
    assert len(token) >= 20
    assert url.endswith(token) or token in url
    _assert_safe(share.json())

    anon = _anon()
    shared = anon.get(f"{BASE}/share/{token}/")
    assert shared.status_code == 200
    assert "REQ-001-S3" in _body(shared)

    invalid = anon.get(f"{BASE}/share/this-token-is-forged-and-invalid-xx/")
    assert invalid.status_code in (404, 403)

    # Cannot exfiltrate repo or uploaded scripts through the share path.
    traversal = anon.get(f"{BASE}/share/{token}/%2e%2e/%2e%2e/manage.py")
    assert traversal.status_code in (404, 403)
    feature = anon.get(f"{BASE}/share/{token}/../uploads/x.feature")
    assert feature.status_code in (404, 403)


def test_adapter_failure_marks_platform_record_failed(online_device, workers_ready, monkeypatch):
    client, _user_obj = _auth()

    def fail_adapter(serial, paths, output_dir):
        return RunSelectedResult(ok=False, message=LLM_NOT_CONFIGURED, run_id="x", device_serial=serial)

    monkeypatch.setattr("apps.app_automation.ai_run.execution._call_adapter", fail_adapter)
    response = client.post(
        f"{BASE}/runs/",
        {"serial": online_device, "script_ids": ["builtin:REQ-001-S1_open_app"]},
        format="json",
    )
    assert response.status_code == 201
    run_id = response.json()["run"]["id"]
    detail = client.get(f"{BASE}/runs/{run_id}/").json()["run"]
    assert detail["status"] == "failed"
    assert detail["error_message"] == LLM_NOT_CONFIGURED
    _assert_safe(detail)


def test_share_and_download_require_completed_report(online_device, workers_ready):
    client, user = _auth()
    run = AiRunExecution.objects.create(user=user, serial=online_device, status=AiRunExecution.STATUS_FAILED)
    assert client.get(f"{BASE}/runs/{run.id}/download/").status_code == 404
    assert client.post(f"{BASE}/runs/{run.id}/share/").status_code == 400

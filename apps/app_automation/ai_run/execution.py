# -*- coding: utf-8 -*-
"""Create and run AiRunExecution records. The AI loop lives in tools.req001.run_selected."""
from __future__ import annotations

import logging
from typing import Optional, Sequence

from django.utils import timezone

from .constants import (
    DEVICE_OFFLINE,
    LLM_NOT_CONFIGURED,
    PLATFORM_FAILED,
    WORKER_NOT_READY,
)
from .devices import serial_is_online
from .locking import locked_device
from .models import AiRunExecution
from .sanitize import sanitize_text
from .scripts import resolve_script_paths
from .storage import relative_to_repo, run_output_dir
from .workers import celery_workers_ready

logger = logging.getLogger(__name__)


def create_run(user, serial: str, script_ids: Sequence[str], *, inspect_fn=None) -> AiRunExecution:
    if not celery_workers_ready(inspect_fn=inspect_fn):
        raise WorkerNotReady(WORKER_NOT_READY)
    if not serial or not serial_is_online(serial):
        raise ValueError(DEVICE_OFFLINE)
    _paths, normalized = resolve_script_paths(user, script_ids)
    run = AiRunExecution.objects.create(
        user=user,
        serial=serial,
        status=AiRunExecution.STATUS_PENDING,
        script_ids=normalized,
    )
    return run


def dispatch_run(run: AiRunExecution) -> AiRunExecution:
    from .tasks import execute_ai_run_task

    async_result = execute_ai_run_task.delay(run.id)
    task_id = getattr(async_result, "id", "") or ""
    run.celery_task_id = task_id
    run.save(update_fields=["celery_task_id", "updated_at"])
    return run


def execute_run(run_id, *, runner=None) -> None:
    """Worker entry: lock device, call the REQ-001 adapter, update the platform record."""
    try:
        run = AiRunExecution.objects.select_related("user").get(id=run_id)
    except AiRunExecution.DoesNotExist:
        logger.error("REQ-002 execution record missing: %s", run_id)
        return

    run.status = AiRunExecution.STATUS_RUNNING
    run.started_at = timezone.now()
    run.error_message = ""
    run.save(update_fields=["status", "started_at", "error_message", "updated_at"])

    try:
        paths, _ = resolve_script_paths(run.user, run.script_ids)
        output_dir = run_output_dir(run.id)
        output_dir.mkdir(parents=True, exist_ok=True)
        with locked_device(run.serial, run.user):
            result = (runner or _call_adapter)(run.serial, paths, output_dir)
        _apply_adapter_result(run, result, output_dir)
    except Exception as exc:
        logger.exception("REQ-002 platform orchestration failed for run %s", run_id)
        _mark_failed(run, exc)


def _call_adapter(serial, paths, output_dir):
    from tools.req001.run_selected import run_selected

    return run_selected(serial, paths, output_dir)


def _apply_adapter_result(run: AiRunExecution, result, output_dir) -> None:
    ok = bool(getattr(result, "ok", False))
    message = sanitize_text(getattr(result, "message", "") or "", fallback=PLATFORM_FAILED)
    cases = _public_cases(getattr(result, "cases", None) or [])
    run.case_results = cases
    run.finished_at = timezone.now()
    if getattr(run, "started_at", None) is None:
        run.started_at = run.finished_at
    report_index = getattr(result, "report_index", None)
    if report_index:
        run.report_relpath = relative_to_repo(output_dir)
    if ok:
        # Fixture assertion failures (e.g. S3) still complete the platform record.
        run.status = AiRunExecution.STATUS_COMPLETED
        run.error_message = ""
        failed = any(c.get("status") != "pass" for c in cases)
        run.result = AiRunExecution.RESULT_FAILED if failed else AiRunExecution.RESULT_PASSED
    else:
        run.status = AiRunExecution.STATUS_FAILED
        run.result = None
        run.error_message = message or PLATFORM_FAILED
    run.save()


def _mark_failed(run: AiRunExecution, exc: BaseException) -> None:
    run.status = AiRunExecution.STATUS_FAILED
    run.result = None
    run.finished_at = timezone.now()
    run.error_message = sanitize_text(str(exc), fallback=PLATFORM_FAILED)
    run.save(update_fields=["status", "result", "finished_at", "error_message", "updated_at"])


def _public_cases(cases) -> list:
    public = []
    for case in cases:
        if hasattr(case, "case_id"):
            public.append(
                {
                    "id": case.case_id,
                    "name": case.name,
                    "status": case.status,
                    "failure_reason": case.failure_reason or "",
                    "screenshots": [str(s) for s in (case.screenshots or []) if not _looks_absolute(str(s))],
                }
            )
        elif isinstance(case, dict):
            public.append(
                {
                    "id": case.get("id") or case.get("case_id") or "",
                    "name": case.get("name") or "",
                    "status": case.get("status") or "",
                    "failure_reason": case.get("failure_reason") or "",
                    "screenshots": [
                        s for s in (case.get("screenshots") or []) if isinstance(s, str) and not _looks_absolute(s)
                    ],
                }
            )
    return public


def _looks_absolute(value: str) -> bool:
    if not value:
        return False
    if value.startswith("/") or (len(value) > 2 and value[1] == ":"):
        return True
    return ".." in value.replace("\\", "/")


class WorkerNotReady(Exception):
    pass

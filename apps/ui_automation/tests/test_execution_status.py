from datetime import timedelta
from types import SimpleNamespace

from django.utils import timezone

from apps.ui_automation.views import planned_tasks_are_settled, settle_execution_record


def _record(tasks, status="running"):
    return SimpleNamespace(
        status=status,
        planned_tasks=tasks,
        logs="start",
        start_time=timezone.now() - timedelta(seconds=5),
        end_time=None,
        duration=None,
    )


def test_running_record_passes_when_every_subtask_is_complete():
    record = _record([
        {"id": 1, "status": "completed"},
        {"id": 2, "status": "completed"},
        {"id": 3, "status": "completed"},
    ])

    assert planned_tasks_are_settled(record.planned_tasks) is True
    assert settle_execution_record(record) is True
    assert record.status == "passed"
    assert record.end_time is not None
    assert "执行完成。" in record.logs
    assert "已完成 3" in record.logs


def test_record_stays_running_while_a_subtask_is_pending():
    record = _record([
        {"id": 1, "status": "completed"},
        {"id": 2, "status": "pending"},
    ])

    assert planned_tasks_are_settled(record.planned_tasks) is False
    assert settle_execution_record(record) is False
    assert record.status == "running"


def test_settled_record_is_not_rewritten():
    record = _record([{"id": 1, "status": "completed"}], status="passed")
    record.logs = "already done"

    assert settle_execution_record(record) is True
    assert record.logs == "already done"

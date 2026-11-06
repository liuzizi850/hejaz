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

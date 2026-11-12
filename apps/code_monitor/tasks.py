from celery import shared_task
from django.core.cache import caches

from apps.code_monitor.pipeline import _TaskRemoved, _save_task, execute_scan


def token_cache_key(task_id: int) -> str:
    return f"code_monitor_git_token:{task_id}"


@shared_task(bind=True, ignore_result=True)
def run_code_monitor_scan(self, task_id: int):
    from apps.code_monitor.models import ScanTask

    token_cache = caches["code_monitor"]
    token = token_cache.get(token_cache_key(task_id)) or ""
    token_cache.delete(token_cache_key(task_id))
    task = ScanTask.objects.get(id=task_id)
    task.celery_task_id = self.request.id or ""
    try:
        _save_task(task, ["celery_task_id", "updated_at"])
    except _TaskRemoved:
        return
    execute_scan(task_id, token=token)

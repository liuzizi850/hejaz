from celery import shared_task
from django.core.cache import caches

from apps.code_monitor.pipeline import execute_scan


def token_cache_key(task_id: int) -> str:
    return f"code_monitor_git_token:{task_id}"


@shared_task(bind=True)
def run_code_monitor_scan(self, task_id: int):
    from apps.code_monitor.models import ScanTask

    token_cache = caches["code_monitor"]
    token = token_cache.get(token_cache_key(task_id)) or ""
    token_cache.delete(token_cache_key(task_id))
    task = ScanTask.objects.get(id=task_id)
    task.celery_task_id = self.request.id or ""
    task.save(update_fields=["celery_task_id", "updated_at"])
    execute_scan(task_id, token=token)

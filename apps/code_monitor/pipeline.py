import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile

from apps.code_monitor.acquire import (
    FETCH_TIMEOUT_SECONDS,
    AcquireError,
    clone_repository,
    redact,
    unzip_archive,
)
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
    _unzip_with_timeout(Path(task.archive.path), root, token)


# unzip_archive has no timeout parameter. A child process can be killed when
# it exceeds FETCH_TIMEOUT_SECONDS. Exit 2 carries AcquireError text on stdout.
# Any other exit keeps the exit code plus redacted, truncated stderr.
_UNZIP_CHILD = f"""
import sys
from pathlib import Path
from {unzip_archive.__module__} import AcquireError, {unzip_archive.__name__}

try:
    {unzip_archive.__name__}(Path(sys.argv[1]), Path(sys.argv[2]))
except AcquireError as exc:
    sys.stdout.buffer.write(str(exc).encode("utf-8"))
    raise SystemExit(2)
"""


def _unzip_with_timeout(archive_path: Path, dest: Path, token: str = "") -> None:
    env = os.environ.copy()
    root = str(settings.BASE_DIR)
    env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        completed = subprocess.run(
            [sys.executable, "-c", _UNZIP_CHILD, str(archive_path), str(dest)],
            cwd=root,
            env=env,
            timeout=FETCH_TIMEOUT_SECONDS,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except subprocess.TimeoutExpired:
        raise AcquireError("克隆或解压超时") from None
    if completed.returncode == 0:
        return
    if completed.returncode == 2:
        message = (completed.stdout or "").strip() or "取代码失败: zip 打不开"
        raise AcquireError(redact(message, token))
    stderr = redact((completed.stderr or "").strip(), token)[:500]
    message = f"取代码失败: 解压进程退出码 {completed.returncode}"
    if stderr:
        message = f"{message}: {stderr}"
    raise AcquireError(message)

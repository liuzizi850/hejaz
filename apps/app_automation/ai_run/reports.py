# -*- coding: utf-8 -*-
"""Serve, zip, and share one run's HTML report assets only (never repo or upload sources)."""
from __future__ import annotations

import io
import mimetypes
import zipfile
from pathlib import Path
from typing import Optional, Set

from django.http import FileResponse, Http404, HttpResponse

from tools.req001.paths import repo_root

from .constants import INVALID_SHARE, REPORT_MISSING, REPORT_NOT_READY, RUN_NOT_FOUND
from .models import AiRunExecution, AiRunShare
from .storage import run_output_dir

_ALLOWED_SUFFIXES: Set[str] = {
    ".html",
    ".htm",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".css",
    ".js",
    ".txt",
}


def report_dir_for(run: AiRunExecution, root: Optional[Path] = None) -> Path:
    root = root or repo_root()
    if not run.report_relpath:
        raise FileNotFoundError(REPORT_NOT_READY)
    candidate = (root / run.report_relpath).resolve()
    allowed_root = (root / "artifacts" / "req002" / "runs").resolve()
    if not _is_under(candidate, allowed_root) or not candidate.is_dir():
        raise FileNotFoundError(REPORT_NOT_READY)
    return candidate


def resolve_report_asset(run: AiRunExecution, relpath: str = "", root: Optional[Path] = None) -> Path:
    directory = report_dir_for(run, root)
    if not directory.is_dir():
        raise FileNotFoundError(REPORT_NOT_READY)
    relative = (relpath or "index.html").replace("\\", "/").lstrip("/")
    if not relative or relative.endswith("/") or ".." in relative.split("/"):
        raise PermissionError(REPORT_MISSING)
    target = (directory / relative).resolve()
    if not _is_under(target, directory):
        raise PermissionError(REPORT_MISSING)
    if not target.is_file():
        raise FileNotFoundError(REPORT_MISSING)
    if target.suffix.lower() not in _ALLOWED_SUFFIXES:
        raise PermissionError(REPORT_MISSING)
    # Never serve uploaded scripts or anything outside the report directory.
    if target.suffix.lower() == ".feature":
        raise PermissionError(REPORT_MISSING)
    return target


def file_response(path: Path) -> FileResponse:
    content_type, _ = mimetypes.guess_type(str(path))
    if path.suffix.lower() in {".html", ".htm"}:
        content_type = "text/html; charset=utf-8"
    return FileResponse(open(path, "rb"), content_type=content_type or "application/octet-stream")


def build_report_zip(run: AiRunExecution, root: Optional[Path] = None) -> bytes:
    directory = report_dir_for(run, root)
    if not directory.is_dir() or not (directory / "index.html").is_file():
        raise FileNotFoundError(REPORT_NOT_READY)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(directory.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in _ALLOWED_SUFFIXES:
                continue
            arcname = path.relative_to(directory).as_posix()
            if arcname.startswith("/") or ".." in arcname or ":" in arcname:
                continue
            zf.write(path, arcname=arcname)
    return buffer.getvalue()


def zip_filename(run: AiRunExecution) -> str:
    return f"ai-run-{run.id}.zip"


def zip_response(run: AiRunExecution, root: Optional[Path] = None) -> HttpResponse:
    data = build_report_zip(run, root)
    response = HttpResponse(data, content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{zip_filename(run)}"'
    return response


def create_share(run: AiRunExecution, user) -> AiRunShare:
    if run.status != AiRunExecution.STATUS_COMPLETED or not (report_dir_for(run) / "index.html").is_file():
        raise FileNotFoundError(REPORT_NOT_READY)
    return AiRunShare.objects.create(execution=run, created_by=user)


def get_share(token: str) -> AiRunShare:
    if not token or len(token) < 16:
        raise AiRunShare.DoesNotExist
    return AiRunShare.objects.select_related("execution").get(token=token)


def share_url_path(token: str) -> str:
    return f"/ai-run-share/{token}"


def http_error(exc: Exception):
    if isinstance(exc, AiRunExecution.DoesNotExist):
        raise Http404(RUN_NOT_FOUND)
    if isinstance(exc, AiRunShare.DoesNotExist):
        raise Http404(INVALID_SHARE)
    if isinstance(exc, FileNotFoundError):
        raise Http404(str(exc) or REPORT_MISSING)
    if isinstance(exc, PermissionError):
        raise Http404(REPORT_MISSING)
    raise exc


def _is_under(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False

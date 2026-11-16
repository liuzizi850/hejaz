# -*- coding: utf-8 -*-
"""Artifact paths for REQ-002. API responses must never include these absolute paths."""
from __future__ import annotations

from pathlib import Path
from typing import Optional
from uuid import UUID

from tools.req001.paths import repo_root


def req002_root(root: Optional[Path] = None) -> Path:
    return (root or repo_root()) / "artifacts" / "req002"


def uploads_dir(user_id, root: Optional[Path] = None) -> Path:
    return req002_root(root) / "uploads" / str(user_id)


def upload_path(user_id, script_id: UUID, root: Optional[Path] = None) -> Path:
    return uploads_dir(user_id, root) / f"{script_id}.feature"


def runs_dir(root: Optional[Path] = None) -> Path:
    return req002_root(root) / "runs"


def run_output_dir(run_id, root: Optional[Path] = None) -> Path:
    return runs_dir(root) / str(run_id)


def relative_to_repo(path: Path, root: Optional[Path] = None) -> str:
    root = root or repo_root()
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name

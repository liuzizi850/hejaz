# -*- coding: utf-8 -*-
"""Repository and fixture path helpers for the REQ-001 toolkit."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional


def repo_root(start: Optional[Path] = None) -> Path:
    """Locate the checkout root that contains manage.py (works in git worktrees)."""
    here = Path(start or __file__).resolve()
    candidates = [here, *here.parents]
    for cand in candidates:
        if (cand / "manage.py").is_file():
            return cand
    raise FileNotFoundError("无法定位仓库根目录（缺少 manage.py）")


def fixtures_dir(root: Optional[Path] = None) -> Path:
    return (root or repo_root()) / "fixtures"


def bdd_dir(root: Optional[Path] = None) -> Path:
    return fixtures_dir(root) / "bdd"


def apk_dir(root: Optional[Path] = None) -> Path:
    return fixtures_dir(root) / "apk"


def artifacts_dir(root: Optional[Path] = None) -> Path:
    return (root or repo_root()) / "artifacts" / "req001"


def primary_checkout_root(root: Optional[Path] = None) -> Optional[Path]:
    """Return the primary git checkout (where an untracked .env usually lives).

    Worktrees do not copy gitignored files. We only use this path to *read*
    local configuration; we never copy, print, or commit it.
    """
    import subprocess

    root = root or repo_root()
    try:
        common = subprocess.check_output(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=str(root),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    common_path = Path(common)
    if not common_path.is_absolute():
        common_path = (root / common_path).resolve()
    else:
        common_path = common_path.resolve()
    # <primary>/.git  or  <primary>/.git/worktrees/<name>
    if common_path.name == ".git":
        return common_path.parent
    if common_path.parent.name == ".git":
        return common_path.parent.parent
    return None


def iter_env_file_candidates(root: Optional[Path] = None) -> Iterable[Path]:
    root = root or repo_root()
    seen = set()
    for path in (root / ".env",):
        if path not in seen:
            seen.add(path)
            yield path
    primary = primary_checkout_root(root)
    if primary is not None:
        path = primary / ".env"
        if path not in seen:
            yield path

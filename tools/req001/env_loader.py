# -*- coding: utf-8 -*-
"""Load KEY=VALUE pairs from local .env files without logging values."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Optional

from tools.req001.paths import iter_env_file_candidates, repo_root

# User-confirmed local credential file for REQ-001. Never copy or commit this file.
# Tests may override the search with REQ001_LLM_ENV_FILE (a temp fixture).
DEFAULT_LLM_ENV_FILE = Path(r"C:\Users\EmmaLiu\.commit-review.env")


def _parse_line(line: str) -> Optional[tuple]:
    raw = line.strip()
    if not raw or raw.startswith("#"):
        return None
    if raw.lower().startswith("export "):
        raw = raw[7:].strip()
    if "=" not in raw:
        return None
    key, _, value = raw.partition("=")
    key = key.strip()
    # Allow names like base_url / DASHSCOPE_API_KEY / COMMIT_REVIEW_MODEL.
    if not key or not all(c.isalnum() or c == "_" for c in key):
        return None
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return key, value


def iter_llm_env_files(root: Optional[Path] = None) -> Iterable[Path]:
    """Project .env first, then the dedicated LLM env file (if present).

    If REQ001_LLM_ENV_FILE is set (unit tests), use that fixture instead of
    the default user-level file so tests never read the real credential file.
    """
    yield from iter_env_file_candidates(root)
    custom = os.environ.get("REQ001_LLM_ENV_FILE", "").strip()
    if custom:
        yield Path(custom)
        return
    yield DEFAULT_LLM_ENV_FILE


def load_env_files(paths: Iterable[Path], override: bool = False) -> None:
    """Set process env from files. Values are never printed or returned."""
    for path in paths:
        try:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            parsed = _parse_line(line)
            if not parsed:
                continue
            key, value = parsed
            if not override and key in os.environ and os.environ[key] != "":
                continue
            os.environ[key] = value


def load_local_env(root: Optional[Path] = None, override: bool = False) -> None:
    root = root or repo_root()
    load_env_files(iter_llm_env_files(root), override=override)

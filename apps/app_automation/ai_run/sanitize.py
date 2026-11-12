# -*- coding: utf-8 -*-
"""Strip secrets, absolute paths, and copy-pasteable commands from tester-facing text."""
from __future__ import annotations

import re
from typing import Any, Iterable

from .constants import LLM_NOT_CONFIGURED, PLATFORM_FAILED

_ABS_PATH = re.compile(
    r"(?:[A-Za-z]:[\\/][^\s\"'<>]+)|(?:/(?:home|Users|Project|workspace|opt|usr|var|root|tmp)[^\s\"'<>]*)"
)
_ENV_NAME = re.compile(
    r"\b(?:DASHSCOPE_API_KEY|OPENAI_API_KEY|REQ001_OPENAI_API_KEY|COMMIT_REVIEW_MODEL|"
    r"REQ001_LLM_ENV_FILE|OPENAI_BASE_URL|REQ001_OPENAI_BASE_URL|BASE_URL|base_url)\b"
)
_COMMAND = re.compile(
    r"\b(?:python(?:3)?|manage\.py|adb(?:\.exe)?|emulator(?:\.exe)?|scrcpy|celery|pytest)\b[^\n]{0,80}",
    re.IGNORECASE,
)
_KEY_LIKE = re.compile(r"(?:sk-|sk-or-v1-|ghp_|github_pat_)[A-Za-z0-9_\-]{8,}")


def looks_like_llm_config_error(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    markers = (
        "llm",
        "dashscope",
        "openai_api_key",
        "commit_review_model",
        "未检测到可用的 llm",
        "缺少 ",
        "未配置执行环境",
        ".commit-review.env",
    )
    return any(m in lowered or m in text for m in markers)


def sanitize_text(text: str, *, fallback: str = PLATFORM_FAILED) -> str:
    if not text:
        return ""
    if looks_like_llm_config_error(text):
        return LLM_NOT_CONFIGURED
    cleaned = _KEY_LIKE.sub("***", text)
    cleaned = _ABS_PATH.sub("（路径已隐藏）", cleaned)
    cleaned = _ENV_NAME.sub("（配置项已隐藏）", cleaned)
    cleaned = _COMMAND.sub("（命令已隐藏）", cleaned)
    cleaned = cleaned.strip()
    if not cleaned or cleaned == "（路径已隐藏）":
        return fallback
    return cleaned[:500]


def contains_forbidden(payload: Any, extra_needles: Iterable[str] = ()) -> bool:
    text = _flatten(payload)
    if _KEY_LIKE.search(text) or _ABS_PATH.search(text):
        return True
    lowered = text.lower()
    for needle in extra_needles:
        if needle and needle.lower() in lowered:
            return True
    return False


def _flatten(payload: Any) -> str:
    if payload is None:
        return ""
    if isinstance(payload, bytes):
        try:
            return payload.decode("utf-8", "replace")
        except Exception:
            return ""
    if isinstance(payload, (dict, list, tuple)):
        return " ".join(_flatten(item) for item in (payload.values() if isinstance(payload, dict) else payload))
    return str(payload)

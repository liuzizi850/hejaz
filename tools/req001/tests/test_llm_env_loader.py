# -*- coding: utf-8 -*-
"""Loader tests use a temporary fixture file with fake values, never the real credential file."""
from pathlib import Path

import pytest

from tools.req001.env_loader import load_local_env, _parse_line
from tools.req001.errors import LlmConfigError
from tools.req001.llm_client import load_llm_config

_CLEAR = (
    "DASHSCOPE_API_KEY",
    "REQ001_OPENAI_API_KEY",
    "OPENAI_API_KEY",
    "base_url",
    "BASE_URL",
    "DASHSCOPE_BASE_URL",
    "REQ001_OPENAI_BASE_URL",
    "OPENAI_BASE_URL",
    "COMMIT_REVIEW_MODEL",
    "REQ001_OPENAI_MODEL",
    "OPENAI_MODEL",
    "REQ001_LLM_MODEL",
    "JUDGE_MODEL",
    "MODEL",
    "REQ001_LLM_ENV_FILE",
)


def _isolate(monkeypatch, tmp_path: Path, body: str) -> Path:
    for key in _CLEAR:
        monkeypatch.delenv(key, raising=False)
    fixture = tmp_path / "review.env"
    fixture.write_text(body, encoding="utf-8")
    monkeypatch.setenv("REQ001_LLM_ENV_FILE", str(fixture))
    # Do not read the repo / primary / user credential files in these tests.
    monkeypatch.setattr("tools.req001.env_loader.iter_env_file_candidates", lambda root=None: [])
    return fixture


def test_parse_line_accepts_lowercase_base_url():
    parsed = _parse_line("base_url=https://example.invalid/v1")
    assert parsed is not None
    assert parsed[0] == "base_url"
    assert parsed[1] == "https://example.invalid/v1"


def test_loads_dashscope_and_base_url_and_commit_review_model(tmp_path, monkeypatch):
    _isolate(
        monkeypatch,
        tmp_path,
        "DASHSCOPE_API_KEY=fake-test-key\n"
        "base_url=https://example.invalid/compatible-mode/v1\n"
        "COMMIT_REVIEW_MODEL=qwen-plus\n",
    )
    load_local_env()
    cfg = load_llm_config(load_files=False)
    assert cfg.api_key == "fake-test-key"
    assert cfg.base_url == "https://example.invalid/compatible-mode/v1"
    assert cfg.model == "qwen-plus"
    summary = cfg.redacted_summary()
    assert "fake-test-key" not in summary
    assert "***" in summary


def test_prefers_file_vars_over_mismatched_openai_env(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "mismatched-openai-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid/openai-mismatch")
    monkeypatch.setenv("OPENAI_MODEL", "wrong-model")
    for key in _CLEAR:
        if key not in {"OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL"}:
            monkeypatch.delenv(key, raising=False)
    fixture = tmp_path / "review.env"
    fixture.write_text(
        "DASHSCOPE_API_KEY=fake-preferred-key\n"
        "base_url=https://example.invalid/compatible-mode/v1\n"
        "COMMIT_REVIEW_MODEL=qwen-plus\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("REQ001_LLM_ENV_FILE", str(fixture))
    monkeypatch.setattr("tools.req001.env_loader.iter_env_file_candidates", lambda root=None: [])
    load_local_env()
    cfg = load_llm_config(load_files=False)
    assert cfg.api_key == "fake-preferred-key"
    assert cfg.base_url == "https://example.invalid/compatible-mode/v1"
    assert cfg.model == "qwen-plus"
    assert cfg.api_key != "mismatched-openai-key"
    assert "openai-mismatch" not in (cfg.base_url or "")
    assert cfg.model != "wrong-model"


def test_defaults_qwen_plus_when_dashscope_key_has_no_model(tmp_path, monkeypatch):
    _isolate(
        monkeypatch,
        tmp_path,
        "DASHSCOPE_API_KEY=fake-test-key\n"
        "base_url=https://example.invalid/compatible-mode/v1\n",
    )
    load_local_env()
    cfg = load_llm_config(load_files=False)
    assert cfg.model == "qwen-plus"

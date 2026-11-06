import subprocess
import zipfile
from pathlib import Path

import pytest

from apps.code_monitor.acquire import (
    FETCH_TIMEOUT_SECONDS,
    AcquireError,
    clone_repository,
    redact,
    unzip_archive,
)


def test_timeout_constant():
    assert FETCH_TIMEOUT_SECONDS == 600


def test_token_is_not_part_of_the_git_command(tmp_path: Path, monkeypatch):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["env"] = kwargs.get("env") or {}
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("apps.code_monitor.acquire.subprocess.run", fake_run)
    clone_repository("https://example.com/repo.git", tmp_path / "repo", token="super-secret-token")
    assert "super-secret-token" not in " ".join(seen["cmd"])
    assert seen["env"]["GIT_CONFIG_VALUE_0"] == "Authorization: Bearer super-secret-token"


def test_clone_timeout_becomes_acquire_error(tmp_path: Path, monkeypatch):
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))

    monkeypatch.setattr("apps.code_monitor.acquire.subprocess.run", fake_run)
    with pytest.raises(AcquireError, match="克隆或解压超时"):
        clone_repository("https://example.com/repo.git", tmp_path / "repo", token="super-secret-token")


def test_redact_removes_token():
    assert redact("failed super-secret-token", "super-secret-token") == "failed ***"


def test_unzip_rejects_path_escape(tmp_path: Path):
    archive = tmp_path / "bad.zip"
    dest = tmp_path / "out"
    dest.mkdir()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../outside.txt", "nope")
    with pytest.raises(AcquireError, match="压缩包路径不安全"):
        unzip_archive(archive, dest)
    assert not (tmp_path / "outside.txt").exists()


def test_unzip_extracts_safe_files(tmp_path: Path):
    archive = tmp_path / "ok.zip"
    dest = tmp_path / "out"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("src/api.js", "axios.get('/api/a')")
    unzip_archive(archive, dest)
    assert (dest / "src" / "api.js").read_text(encoding="utf-8") == "axios.get('/api/a')"

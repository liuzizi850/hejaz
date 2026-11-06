import os
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
    assert seen["cmd"][:5] == ["git", "clone", "--depth", "1", "--"]
    assert seen["cmd"][5] == "https://super-secret-token@example.com/repo.git"
    assert seen["cmd"][6] == str(tmp_path / "repo")
    assert all(part != "super-secret-token" for part in seen["cmd"])
    assert "super-secret-token" not in seen["cmd"][-1]
    env = seen["env"]
    assert env is not os.environ
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    for key, value in env.items():
        if key == "GIT_TERMINAL_PROMPT":
            continue
        assert os.environ.get(key) == value


def test_clone_timeout_becomes_acquire_error(tmp_path: Path, monkeypatch):
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))

    monkeypatch.setattr("apps.code_monitor.acquire.subprocess.run", fake_run)
    with pytest.raises(AcquireError, match="克隆或解压超时"):
        clone_repository("https://example.com/repo.git", tmp_path / "repo", token="super-secret-token")


def test_redact_removes_token():
    assert redact("failed super-secret-token", "super-secret-token") == "failed ***"
    assert redact("https://a%2Fb@example.com", "a/b") == "https://***@example.com"


@pytest.mark.parametrize("url", [
    "file:///tmp/repo.git",
    "FILE:///tmp/repo.git",
    "/tmp/repo.git",
    r"C:\repo",
    "./repo.git",
    "--upload-pack=evil",
    "-c",
    "ext::sh -c evil",
    "ssh://git@example.com/repo.git",
    "git@example.com:org/repo.git",
    "git://example.com/repo.git",
    "http://",
    "https://",
])
def test_clone_rejects_unsafe_git_url(url, tmp_path: Path, monkeypatch):
    def fail_run(*args, **kwargs):
        raise AssertionError("git should not run")

    monkeypatch.setattr("apps.code_monitor.acquire.subprocess.run", fail_run)
    with pytest.raises(AcquireError):
        clone_repository(url, tmp_path / "repo", token="super-secret-token")


def test_clone_error_redacts_token_in_url(tmp_path: Path, monkeypatch):
    def fake_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(128, cmd, stderr=f"fatal: unable to access '{cmd[5]}'")

    monkeypatch.setattr("apps.code_monitor.acquire.subprocess.run", fake_run)
    with pytest.raises(AcquireError) as caught:
        clone_repository("https://example.com/repo.git", tmp_path / "repo", token="super-secret-token")
    message = str(caught.value)
    assert "super-secret-token" not in message
    assert "***" in message


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

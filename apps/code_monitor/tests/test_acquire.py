import os
import subprocess
import zipfile
from pathlib import Path

import pytest

from apps.code_monitor.acquire import (
    FETCH_TIMEOUT_SECONDS,
    AcquireError,
    clone_repository,
    _extended_path,
    redact,
    unzip_archive,
)


def test_timeout_constant():
    assert FETCH_TIMEOUT_SECONDS == 600


def test_token_is_not_part_of_the_git_command(tmp_path: Path, monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append({"cmd": list(cmd), "env": kwargs.get("env") or {}})
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("apps.code_monitor.acquire.subprocess.run", fake_run)
    dest = tmp_path / "repo"
    plain_url = "https://example.com/repo.git"
    clone_repository(plain_url, dest, token="super-secret-token")
    assert len(calls) == 2
    clone_cmd = calls[0]["cmd"]
    assert clone_cmd[:7] == ["git", "-c", "credential.helper=", "clone", "--depth", "1", "--"]
    assert clone_cmd[7] == "https://super-secret-token@example.com/repo.git"
    assert clone_cmd[8] == str(dest)
    set_url_cmd = calls[1]["cmd"]
    assert set_url_cmd == ["git", "-C", str(dest), "remote", "set-url", "origin", plain_url]
    assert "super-secret-token" not in set_url_cmd[-1]
    for call in calls:
        assert all(part != "super-secret-token" for part in call["cmd"])
        for part in call["cmd"]:
            if part == clone_cmd[7]:
                continue
            assert "super-secret-token" not in part
        env = call["env"]
        assert env is not os.environ
        assert env["GIT_TERMINAL_PROMPT"] == "0"
        for key, value in env.items():
            if key == "GIT_TERMINAL_PROMPT":
                continue
            assert os.environ.get(key) == value


def test_gitlab_token_is_sent_as_password(tmp_path: Path, monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("apps.code_monitor.acquire.subprocess.run", fake_run)
    clone_repository(
        "https://gitlab.com/group/repo.git",
        tmp_path / "repo",
        token="super-secret-token",
    )
    assert calls[0][7] == "https://oauth2:super-secret-token@gitlab.com/group/repo.git"
    assert calls[1][-1] == "https://gitlab.com/group/repo.git"


def test_clone_without_token_does_not_set_url(tmp_path: Path, monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("apps.code_monitor.acquire.subprocess.run", fake_run)
    dest = tmp_path / "repo"
    url = "https://example.com/repo.git"
    clone_repository(url, dest)
    assert calls == [[
        "git", "-c", "credential.helper=",
        "clone", "--depth", "1", "--",
        url,
        str(dest),
    ]]
    assert "set-url" not in calls[0]


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
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        clone_url = cmd[cmd.index("--") + 1]
        raise subprocess.CalledProcessError(128, cmd, stderr=f"fatal: unable to access '{clone_url}'")

    monkeypatch.setattr("apps.code_monitor.acquire.subprocess.run", fake_run)
    with pytest.raises(AcquireError) as caught:
        clone_repository("https://example.com/repo.git", tmp_path / "repo", token="super-secret-token")
    message = str(caught.value)
    assert "super-secret-token" not in message
    assert "***" in message
    assert len(calls) == 1
    assert "set-url" not in calls[0]


def test_unzip_rejects_path_escape(tmp_path: Path):
    archive = tmp_path / "bad.zip"
    dest = tmp_path / "out"
    dest.mkdir()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../outside.txt", "nope")
    with pytest.raises(AcquireError, match="压缩包路径不安全"):
        unzip_archive(archive, dest)
    assert not (tmp_path / "outside.txt").exists()


def test_unzip_extracts_long_paths(tmp_path: Path):
    archive = tmp_path / "long.zip"
    dest = tmp_path / "out"
    relative = "/".join(["b" * 40] * 8) + "/c.js"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("src/api.js", "axios.get('/api/a')")
        zf.writestr(relative, "console.log(1)")
    unzip_archive(archive, dest)
    assert (dest / "src" / "api.js").read_text(encoding="utf-8") == "axios.get('/api/a')"
    target = dest.joinpath(*relative.split("/"))
    assert Path(_extended_path(target)).read_text(encoding="utf-8") == "console.log(1)"


def test_unzip_rewrites_windows_illegal_names(tmp_path: Path):
    archive = tmp_path / "names.zip"
    dest = tmp_path / "out"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("src/a:b.js", "axios.get('/api/a')")
        zf.writestr("src/AUX.txt", "reserved")
    unzip_archive(archive, dest)
    assert (dest / "src" / "a_b.js").read_text(encoding="utf-8") == "axios.get('/api/a')"
    assert (dest / "src" / "_AUX.txt").read_text(encoding="utf-8") == "reserved"


def test_unzip_extracts_safe_files(tmp_path: Path):
    archive = tmp_path / "ok.zip"
    dest = tmp_path / "out"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("src/api.js", "axios.get('/api/a')")
    unzip_archive(archive, dest)
    assert (dest / "src" / "api.js").read_text(encoding="utf-8") == "axios.get('/api/a')"

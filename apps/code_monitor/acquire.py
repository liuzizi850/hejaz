import os
import subprocess
import zipfile
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

FETCH_TIMEOUT_SECONDS = 600
_GIT_URL_ERROR = "只允许带主机名的 http 或 https Git 地址"


class AcquireError(Exception):
    pass


def redact(text: str, token: str) -> str:
    if not text:
        return ""
    if not token:
        return text
    variants = {token, quote(token, safe="")}
    redacted = text
    for variant in sorted((item for item in variants if item), key=len, reverse=True):
        redacted = redacted.replace(variant, "***")
    return redacted


def ensure_http_git_url(url: str) -> str:
    text = (url or "").strip()
    if not text or text.startswith("-") or any(char in text for char in "\x00\r\n"):
        raise AcquireError(_GIT_URL_ERROR)
    lowered = text.casefold()
    if lowered.startswith(("ext::", "file:", "ssh:", "git:", "git+")):
        raise AcquireError(_GIT_URL_ERROR)
    if "://" not in text:
        raise AcquireError(_GIT_URL_ERROR)
    parsed = urlsplit(text)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise AcquireError(_GIT_URL_ERROR)
    return text


def _clone_url(url: str, token: str) -> str:
    if not token:
        return url
    parsed = urlsplit(url)
    host = parsed.hostname
    if not host:
        raise AcquireError(_GIT_URL_ERROR)
    if ":" in host:
        host = f"[{host}]"
    netloc = f"{quote(token, safe='')}@{host}"
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def clone_repository(url: str, dest: Path, token: str = "", timeout: int = FETCH_TIMEOUT_SECONDS) -> None:
    url = ensure_http_git_url(url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["git", "clone", "--depth", "1", "--", _clone_url(url, token), str(dest)]
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        subprocess.run(
            cmd,
            env=env,
            timeout=timeout,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired as exc:
        raise AcquireError("克隆或解压超时") from exc
    except subprocess.CalledProcessError as exc:
        detail = redact((exc.stderr or exc.stdout or "").strip(), token)
        raise AcquireError(f"取代码失败: {detail or 'git clone 失败'}") from exc


def unzip_archive(archive_path: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(archive_path) as zf:
            dest_resolved = dest.resolve()
            for info in zf.infolist():
                target = (dest_resolved / info.filename).resolve()
                try:
                    target.relative_to(dest_resolved)
                except ValueError:
                    raise AcquireError("压缩包路径不安全")
            zf.extractall(dest)
    except AcquireError:
        raise
    except (zipfile.BadZipFile, OSError) as exc:
        raise AcquireError("取代码失败: zip 打不开") from exc

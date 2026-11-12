import os
import shutil
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


def _gitlab_host(host: str) -> bool:
    return "gitlab" in host.lower().rstrip(".").split(".")


def _clone_url(url: str, token: str) -> str:
    if not token:
        return url
    parsed = urlsplit(url)
    host = parsed.hostname
    if not host:
        raise AcquireError(_GIT_URL_ERROR)
    # GitLab 把令牌当作密码，用户名任意非空。其他主机沿用令牌即用户名。
    userinfo = quote(token, safe="")
    if _gitlab_host(host):
        userinfo = f"oauth2:{userinfo}"
    if ":" in host:
        host = f"[{host}]"
    netloc = f"{userinfo}@{host}"
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def clone_repository(url: str, dest: Path, token: str = "", timeout: int = FETCH_TIMEOUT_SECONDS) -> None:
    url = ensure_http_git_url(url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    commands = [[
        "git", "-c", "credential.helper=",
        "clone", "--depth", "1", "--",
        _clone_url(url, token),
        str(dest),
    ]]
    if token:
        commands.append(["git", "-C", str(dest), "remote", "set-url", "origin", url])
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    for cmd in commands:
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


def _extended_path(path: Path) -> str:
    text = os.path.abspath(path)
    if os.name != "nt" or text.startswith("\\\\?\\"):
        return text
    if text.startswith("\\\\"):
        return "\\\\?\\UNC\\" + text[2:]
    return "\\\\?\\" + text


def _member_target(dest: Path, name: str) -> Path:
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or (len(normalized) >= 2 and normalized[1] == ":"):
        raise AcquireError("压缩包路径不安全")
    parts = []
    for part in normalized.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise AcquireError("压缩包路径不安全")
        parts.append(part)
    target = dest
    for part in parts:
        target = target / part
    return target


def unzip_archive(archive_path: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(archive_path) as zf:
            for info in zf.infolist():
                target = _member_target(dest, info.filename)
                if target == dest:
                    continue
                location = _extended_path(target)
                if info.is_dir() or info.filename.endswith("/"):
                    os.makedirs(location, exist_ok=True)
                    continue
                os.makedirs(_extended_path(target.parent), exist_ok=True)
                with zf.open(info, "r") as source, open(location, "wb") as output:
                    shutil.copyfileobj(source, output)
    except AcquireError:
        raise
    except (zipfile.BadZipFile, OSError) as exc:
        raise AcquireError("取代码失败: zip 打不开") from exc

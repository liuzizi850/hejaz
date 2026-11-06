import subprocess
import zipfile
from pathlib import Path

FETCH_TIMEOUT_SECONDS = 600


class AcquireError(Exception):
    pass


def redact(text: str, token: str) -> str:
    if token and text and token in text:
        return text.replace(token, "***")
    return text or ""


def clone_repository(url: str, dest: Path, token: str = "", timeout: int = FETCH_TIMEOUT_SECONDS) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["git", "clone", "--depth", "1", url, str(dest)]
    env = dict(**__import__("os").environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    if token:
        env["GIT_CONFIG_COUNT"] = "1"
        env["GIT_CONFIG_KEY_0"] = "http.extraheader"
        env["GIT_CONFIG_VALUE_0"] = f"Authorization: Bearer {token}"
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

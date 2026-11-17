# -*- coding: utf-8 -*-
SERVICE_COMPONENT = "com.testhub.recorder/com.testhub.recorder.RecorderService"
RECORDER_PORT = 27183


def _configured_adb_path():
    try:
        from django.conf import settings
        if not settings.configured:
            return ""
        from apps.app_automation.models import AppTestConfig
        config = AppTestConfig.objects.first()
        return (config.adb_path or "") if config else ""
    except Exception:
        return ""


def _sdk_adb_candidates():
    import os
    roots = []
    for key in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        value = os.environ.get(key)
        if value:
            roots.append(value)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        roots.append(os.path.join(local, "Android", "Sdk"))
    home = os.path.expanduser("~")
    roots.extend([
        os.path.join(home, "AppData", "Local", "Android", "Sdk"),
        os.path.join(home, "Library", "Android", "sdk"),
        os.path.join(home, "Android", "Sdk"),
    ])
    candidates = []
    for root in roots:
        candidates.append(os.path.join(root, "platform-tools", "adb.exe"))
        candidates.append(os.path.join(root, "platform-tools", "adb"))
    return candidates


def adb_executable():
    """配置里的路径优先；命令名 adb 不在 PATH 时改用本机 Android SDK。"""
    import os
    import shutil
    configured = _configured_adb_path()
    if configured and configured != "adb" and (os.path.isfile(configured) or shutil.which(configured)):
        return configured
    found = shutil.which("adb")
    if found:
        return found
    for candidate in _sdk_adb_candidates():
        if os.path.isfile(candidate):
            return candidate
    return configured or "adb"


def ensure_adb_on_path():
    import os
    executable = adb_executable()
    folder = os.path.dirname(executable)
    if not folder or not os.path.isdir(folder):
        return executable
    parts = os.environ.get("PATH", "").split(os.pathsep)
    if folder not in parts:
        os.environ["PATH"] = folder + os.pathsep + os.environ.get("PATH", "")
    return executable


def accessibility_enabled(command_output):
    return SERVICE_COMPONENT in (command_output or "")


def reverse_argument(django_port=8000):
    return ["reverse", "tcp:%s" % RECORDER_PORT, "tcp:%s" % int(django_port)]


def service_enabled(device_id, command_output=None):
    if isinstance(command_output, str):
        return accessibility_enabled(command_output)
    import subprocess
    ensure_adb_on_path()
    try:
        result = subprocess.run(
            [
                "adb", "-s", device_id, "shell",
                "settings", "get", "secure", "enabled_accessibility_services",
            ],
            capture_output=True,
            timeout=5,
        )
        output = result.stdout.decode("utf-8", errors="ignore") if result.stdout else ""
        return accessibility_enabled(output)
    except (OSError, subprocess.TimeoutExpired):
        return False


def apply_reverse(device_id):
    return _run_adb(["adb", "-s", device_id] + reverse_argument(8000))


def ingest_url(session_id):
    return "http://127.0.0.1:%s/api/app-automation/recording-sessions/%s/events/" % (
        RECORDER_PORT, session_id,
    )


def start_broadcast_args(device_id, session_id):
    return [
        "adb", "-s", device_id, "shell", "am", "broadcast",
        "-a", "com.testhub.recorder.START",
        "--es", "ingestUrl", ingest_url(session_id),
    ]


def stop_broadcast_args(device_id):
    return [
        "adb", "-s", device_id, "shell", "am", "broadcast",
        "-a", "com.testhub.recorder.STOP",
    ]


def _run_adb(args):
    import subprocess
    ensure_adb_on_path()
    try:
        result = subprocess.run(args, capture_output=True, timeout=5)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def broadcast_start(device_id, session_id):
    return _run_adb(start_broadcast_args(device_id, session_id))


def broadcast_stop(device_id):
    return _run_adb(stop_broadcast_args(device_id))


def parse_ui_dump(xml_text, screen_width, screen_height):
    import re
    texts = []
    selectors = []
    for attrs in re.findall(r"<node\s+([^>]+)/?>", xml_text or ""):
        def attr(name):
            found = re.search(name + r'="([^"]*)"', attrs)
            return found.group(1) if found else ""
        text = attr("text")
        if text:
            texts.append(text)
        bounds = attr("bounds")
        pair = re.findall(r"\d+", bounds)
        relative = {}
        if len(pair) == 4 and screen_width and screen_height:
            left, top, right, bottom = [int(item) for item in pair]
            relative = {
                "x": left / float(screen_width),
                "y": top / float(screen_height),
                "w": (right - left) / float(screen_width),
                "h": (bottom - top) / float(screen_height),
            }
        selectors.append({
            "resource_id": attr("resource-id"),
            "content_desc": attr("content-desc"),
            "text": text,
            "class_name": attr("class"),
            "bounds": relative,
        })
    return {"texts": texts, "selectors": selectors}


def safe_device_filename(device_id):
    import re
    return re.sub(r"[^a-zA-Z0-9._-]", "_", device_id or "")


def bounds_complete(bounds):
    if not isinstance(bounds, dict):
        return False
    return all(key in bounds and bounds[key] not in (None, "") for key in ("x", "y", "w", "h"))


def pixel_box(width, height, bounds):
    width = max(int(width), 1)
    height = max(int(height), 1)
    x = int(float(bounds["x"]) * width)
    y = int(float(bounds["y"]) * height)
    w = int(float(bounds["w"]) * width)
    h = int(float(bounds["h"]) * height)
    if w < 0:
        x, w = x + w, -w
    if h < 0:
        y, h = y + h, -h
    x = max(0, min(x, width - 1))
    y = max(0, min(y, height - 1))
    w = max(1, min(w, width - x))
    h = max(1, min(h, height - y))
    return x, y, w, h


def crop_fraction(image, bounds):
    if hasattr(image, "crop") and hasattr(image, "size"):
        width, height = image.size
        x, y, w, h = pixel_box(width, height, bounds)
        return image.crop((x, y, x + w, y + h))
    height, width = image.shape[:2]
    x, y, w, h = pixel_box(width, height, bounds)
    return image[y:y + h, x:x + w]


def _decode_image(png_bytes):
    try:
        import cv2
        import numpy as np
        image = cv2.imdecode(np.frombuffer(png_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("无法解码截图")
        return image
    except ImportError:
        from PIL import Image
        import io
        return Image.open(io.BytesIO(png_bytes)).convert("RGB")


def _encode_image(path, image):
    if hasattr(image, "save"):
        image.save(path, format="PNG")
        return
    import cv2
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("无法保存截图")
    with open(path, "wb") as handle:
        handle.write(encoded.tobytes())


def capture_png(device_id):
    import subprocess
    ensure_adb_on_path()
    return subprocess.check_output(
        ["adb", "-s", device_id, "exec-out", "screencap", "-p"],
        timeout=8,
    )


def capture_start_screen(device_id, session_id):
    import os
    from django.conf import settings
    directory = os.path.join(settings.MEDIA_ROOT, "app-automation", "recordings", "sessions")
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "%s.png" % session_id)
    with open(path, "wb") as handle:
        handle.write(capture_png(device_id))
    return path


def save_step_image(device_id, session_id, order, bounds=None, png_bytes=None):
    import os
    from django.conf import settings
    if png_bytes is None:
        png_bytes = capture_png(device_id)
    directory = os.path.join(
        settings.MEDIA_ROOT, "app-automation", "recordings", "sessions", str(session_id)
    )
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "%s.png" % order)
    if bounds:
        _encode_image(path, crop_fraction(_decode_image(png_bytes), bounds))
    else:
        with open(path, "wb") as handle:
            handle.write(png_bytes)
    return path


def copy_case_start_screen(source, case_id):
    import os
    import shutil
    from django.conf import settings
    if not source or not os.path.isfile(source):
        return source or ""
    directory = os.path.join(settings.MEDIA_ROOT, "app-automation", "recordings", str(case_id))
    os.makedirs(directory, exist_ok=True)
    dest = os.path.join(directory, "start.png")
    if os.path.abspath(source) != os.path.abspath(dest):
        shutil.copyfile(source, dest)
    return dest


def media_search_roots():
    """当前服务的 media，以及 worktree 对应主仓库的 media。"""
    import os
    from pathlib import Path
    from django.conf import settings

    roots = []

    def add(path):
        if not path:
            return
        absolute = os.path.abspath(path)
        if absolute not in roots and os.path.isdir(absolute):
            roots.append(absolute)

    add(getattr(settings, "MEDIA_ROOT", ""))
    base = Path(getattr(settings, "BASE_DIR", "")).resolve()
    if base.parent.name == ".worktrees":
        add(base.parent.parent / "media")
    return roots


def to_media_url(path):
    import os
    from django.conf import settings
    if not path:
        return ""
    target = os.path.abspath(path)
    prefix = settings.MEDIA_URL or "/media/"
    if not prefix.endswith("/"):
        prefix += "/"
    for root in media_search_roots():
        try:
            rel = os.path.relpath(target, root)
        except ValueError:
            continue
        if rel.startswith(".."):
            continue
        return prefix + rel.replace("\\", "/")
    return ""


def resolve_media_file(relative_path):
    """在已知 media 目录里找文件，拒绝跳出目录。"""
    import os
    relative = (relative_path or "").replace("\\", "/").lstrip("/")
    if not relative or any(part in ("", "..") for part in relative.split("/")):
        return ""
    for root in media_search_roots():
        full = os.path.abspath(os.path.join(root, *relative.split("/")))
        root_abs = os.path.abspath(root)
        if not full.startswith(root_abs + os.sep):
            continue
        if os.path.isfile(full):
            return full
    return ""


def hierarchy_xml(command_output, xml):
    """Ignore a failed dump. An error leaves the previous file in place, which is the wrong page."""
    if "ERROR" in (command_output or "").upper():
        return ""
    body = xml or ""
    if "<hierarchy" not in body and "<node" not in body:
        return ""
    return body


def read_ui_dump(device_id):
    """执行 adb shell uiautomator dump 后读回 XML。失败返回空字符串。"""
    import subprocess
    ensure_adb_on_path()
    remote = "/sdcard/testhub-uidump.xml"
    for _attempt in range(2):
        subprocess.run(
            ["adb", "-s", device_id, "shell", "rm", "-f", remote],
            capture_output=True,
            timeout=8,
        )
        try:
            dump = subprocess.run(
                ["adb", "-s", device_id, "shell", "uiautomator", "dump", remote],
                capture_output=True,
                timeout=8,
            )
        except subprocess.TimeoutExpired:
            continue
        output = ((dump.stdout or b"") + (dump.stderr or b"")).decode("utf-8", "replace")
        if dump.returncode != 0:
            continue
        try:
            read = subprocess.run(
                ["adb", "-s", device_id, "shell", "cat", remote],
                capture_output=True,
                timeout=8,
            )
        except subprocess.TimeoutExpired:
            continue
        xml = hierarchy_xml(output, (read.stdout or b"").decode("utf-8", "replace"))
        if xml:
            return xml
    return ""

# -*- coding: utf-8 -*-
SERVICE_COMPONENT = "com.testhub.recorder/com.testhub.recorder.RecorderService"
RECORDER_PORT = 27183


def accessibility_enabled(command_output):
    return SERVICE_COMPONENT in (command_output or "")


def reverse_argument(django_port=8000):
    return ["reverse", "tcp:%s" % RECORDER_PORT, "tcp:%s" % int(django_port)]


def service_enabled(device_id, command_output=None):
    if isinstance(command_output, str):
        return accessibility_enabled(command_output)
    import subprocess
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


def to_media_url(path):
    import os
    from django.conf import settings
    if not path:
        return ""
    root = os.path.abspath(settings.MEDIA_ROOT)
    target = os.path.abspath(path)
    try:
        rel = os.path.relpath(target, root)
    except ValueError:
        return ""
    if rel.startswith(".."):
        return ""
    prefix = settings.MEDIA_URL or "/media/"
    if not prefix.endswith("/"):
        prefix += "/"
    return prefix + rel.replace("\\", "/")


def read_ui_dump(device_id):
    """执行 adb shell uiautomator dump 后读回 XML。失败返回空字符串。"""
    import subprocess
    remote = "/sdcard/testhub-uidump.xml"
    dump = subprocess.run(["adb", "-s", device_id, "shell", "uiautomator", "dump", remote], capture_output=True)
    if dump.returncode != 0:
        return ""
    read = subprocess.run(["adb", "-s", device_id, "shell", "cat", remote], capture_output=True)
    if read.returncode != 0:
        return ""
    return read.stdout.decode("utf-8", errors="ignore")

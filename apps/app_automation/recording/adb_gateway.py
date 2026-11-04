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
    import subprocess
    try:
        result = subprocess.run(
            ["adb", "-s", device_id] + reverse_argument(8000),
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


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


def capture_start_screen(device_id):
    import os
    import subprocess
    from django.conf import settings
    directory = os.path.join(settings.MEDIA_ROOT, "app-automation", "recordings", "starts")
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "%s.png" % device_id)
    data = subprocess.check_output(["adb", "-s", device_id, "exec-out", "screencap", "-p"])
    with open(path, "wb") as handle:
        handle.write(data)
    return path


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

# -*- coding: utf-8 -*-
import os
import re
import subprocess
import threading
import time

import cv2
import numpy as np
from airtest.core.cv import Template
from django.conf import settings

from apps.app_automation.recording.adb_gateway import parse_ui_dump, read_ui_dump
from apps.app_automation.recording.replay import ScreenRecordError, replay_event_chain
from apps.app_automation.recording.report_pack import build_result_zip, write_report_docx


def segment_count(elapsed_seconds, limit=180):
    if elapsed_seconds <= 0:
        return 0
    return int((elapsed_seconds + limit - 1) // limit)


def video_names(elapsed_seconds, limit=180):
    return ["video-%s.mp4" % index for index in range(1, segment_count(elapsed_seconds, limit) + 1)]


class EventChainRunner:
    def run(self, execution_id, device=None):
        from apps.app_automation.models import AppTestExecution
        execution = AppTestExecution.objects.get(id=execution_id)
        case = execution.test_case
        if device is None:
            device = AdbEventDevice(execution.device.device_id, execution_id)
        chain = case.event_chain if isinstance(case.event_chain, dict) else {}
        result = replay_event_chain(chain.get("steps") or [], case.start_screen, device)
        if result["start_screen_mismatch"]:
            execution.error_message = "开始界面不匹配\n当前屏: %s\n开始界面: %s" % (
                result["current_screen"], result["start_screen"]
            )
            execution.result_bundle_path = ""
            execution.save(update_fields=["error_message", "result_bundle_path", "updated_at"])
            return result
        bundle_dir = os.path.join(settings.MEDIA_ROOT, "app-automation", "results", str(execution_id))
        os.makedirs(bundle_dir, exist_ok=True)
        docx_path = os.path.join(bundle_dir, "report.docx")
        try:
            write_report_docx(
                docx_path,
                result["steps"],
                [os.path.basename(path) for path in result["videos"]],
                result["screenrecord_error"],
            )
            zip_path = os.path.join(bundle_dir, "result.zip")
            shots = [step.get("screenshot") for step in result["steps"] if step.get("screenshot")]
            build_result_zip(zip_path, docx_path, shots, result["videos"])
            result["result_bundle_path"] = zip_path
        except Exception:
            result["result_bundle_path"] = ""
            execution.error_message = "报告未生成"
            execution.save(update_fields=["error_message", "updated_at"])
            return result
        execution.result_bundle_path = result["result_bundle_path"]
        execution.save(update_fields=["result_bundle_path", "updated_at"])
        return result


class AdbEventDevice:
    def __init__(self, device_id, execution_id):
        self.device_id = device_id
        self.execution_id = execution_id
        self._videos = []
        self._stop = False
        self._record_error = ""
        self._last_match = None
        self._size = None

    def _dir(self):
        directory = os.path.join(settings.MEDIA_ROOT, "app-automation", "results", str(self.execution_id))
        os.makedirs(directory, exist_ok=True)
        return directory

    def _screen_size(self):
        if self._size:
            return self._size
        width, height = 1080, 1920
        try:
            output = subprocess.check_output(
                ["adb", "-s", self.device_id, "shell", "wm", "size"],
                stderr=subprocess.STDOUT,
            )
            text = output.decode("utf-8", errors="ignore")
            found = re.findall(r"(\d+)x(\d+)", text)
            if found:
                width, height = int(found[-1][0]), int(found[-1][1])
        except (OSError, subprocess.CalledProcessError, ValueError):
            pass
        self._size = (width, height)
        return self._size

    def _point(self, node):
        node = node or {}
        bounds = node.get("bounds") or {}
        width, height = self._screen_size()
        try:
            if all(key in bounds for key in ("x", "y", "w", "h")):
                x = (float(bounds["x"]) + float(bounds["w"]) / 2.0) * width
                y = (float(bounds["y"]) + float(bounds["h"]) / 2.0) * height
                return x, y
        except (TypeError, ValueError):
            pass
        last = self._last_match
        if isinstance(last, (tuple, list)) and len(last) >= 2:
            return float(last[0]), float(last[1])
        return width / 2.0, height / 2.0

    def _input(self, *args):
        subprocess.check_call(["adb", "-s", self.device_id, "shell", "input", *[str(arg) for arg in args]])

    def _imread(self, path):
        if not path or not os.path.isfile(path):
            return None
        data = np.fromfile(path, dtype=np.uint8)
        if data.size == 0:
            return None
        return cv2.imdecode(data, cv2.IMREAD_COLOR)

    def _imwrite(self, path, image):
        ok, encoded = cv2.imencode(".png", image)
        if not ok:
            return False
        with open(path, "wb") as handle:
            handle.write(encoded.tobytes())
        return True

    def screenshot(self, name):
        path = os.path.join(self._dir(), "%s.png" % name)
        data = subprocess.check_output(["adb", "-s", self.device_id, "exec-out", "screencap", "-p"])
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def match_images(self, expected, actual, crop_top_ratio):
        left = self._imread(expected)
        right = self._imread(actual)
        if left is None or right is None:
            return False
        top = int(left.shape[0] * crop_top_ratio)
        if top < 0 or top >= left.shape[0] or top >= right.shape[0]:
            return False
        left = left[top:, :, :]
        right = right[top:, :, :]
        if left.size == 0 or right.size == 0:
            return False
        cropped_path = os.path.join(self._dir(), "expected-crop.png")
        if not self._imwrite(cropped_path, left):
            return False
        try:
            return Template(cropped_path).match_in(right) is not None
        except Exception:
            return False

    def find_nodes(self):
        xml = read_ui_dump(self.device_id)
        width, height = self._screen_size()
        return parse_ui_dump(xml, width, height).get("selectors") or []

    def match_template(self, template_path):
        screen = self._imread(self.screenshot("template-screen"))
        self._last_match = None
        if screen is None or not template_path:
            return False
        try:
            found = Template(template_path).match_in(screen)
        except Exception:
            return False
        self._last_match = found
        return found is not None

    def click(self, node):
        x, y = self._point(node)
        self._input("tap", int(round(x)), int(round(y)))

    def long_press(self, node, duration_ms):
        x, y = self._point(node)
        duration = int(duration_ms or 0)
        if duration <= 0:
            duration = 1000
        xi, yi = int(round(x)), int(round(y))
        self._input("swipe", xi, yi, xi, yi, duration)

    def swipe(self, node, direction, distance):
        x, y = self._point(node)
        width, height = self._screen_size()
        span = float(distance or 0)
        dx, dy = 0.0, 0.0
        if direction == "down":
            dy = span * height
        elif direction == "left":
            dx = -span * width
        elif direction == "right":
            dx = span * width
        else:
            dy = -span * height
        x2 = min(max(x + dx, 1), max(width - 1, 1))
        y2 = min(max(y + dy, 1), max(height - 1, 1))
        self._input("swipe", int(round(x)), int(round(y)), int(round(x2)), int(round(y2)), 300)

    def input_text(self, node, text):
        self.click(node)
        encoded = (text or "").replace(" ", "%s")
        self._input("text", encoded)

    def wait_ms(self, duration_ms):
        time.sleep(max(int(duration_ms or 0), 0) / 1000.0)

    def text_exists(self, text):
        needle = text or ""
        if not needle:
            return False
        return any(needle in (node.get("text") or "") for node in self.find_nodes())

    def start_screenrecord(self):
        self._stop = False
        self._record_error = ""
        self._videos = []
        self._thread = threading.Thread(target=self._record_loop, daemon=True)
        self._thread.start()
        time.sleep(0.5)
        if not self._videos and self._record_error:
            raise ScreenRecordError("录屏失败")

    def _record_loop(self):
        index = 1
        while not self._stop:
            remote = "/sdcard/testhub-video-%s.mp4" % index
            try:
                proc = subprocess.Popen(
                    ["adb", "-s", self.device_id, "shell", "screenrecord", "--time-limit", "180", remote]
                )
            except OSError:
                self._record_error = "录屏失败"
                return
            while proc.poll() is None and not self._stop:
                time.sleep(0.5)
            if proc.poll() is None:
                subprocess.call(["adb", "-s", self.device_id, "shell", "pkill", "-l", "2", "screenrecord"])
                try:
                    proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    subprocess.call(["adb", "-s", self.device_id, "shell", "killall", "-2", "screenrecord"])
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        try:
                            proc.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            pass
            local = os.path.join(self._dir(), "video-%s.mp4" % index)
            pulled = subprocess.call(["adb", "-s", self.device_id, "pull", remote, local])
            if pulled != 0:
                self._record_error = "录屏失败"
                return
            self._videos.append(local)
            index += 1

    def stop_screenrecord(self):
        self._stop = True
        self._thread.join(timeout=15)
        return list(self._videos)

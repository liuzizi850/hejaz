# -*- coding: utf-8 -*-
import subprocess
import threading

from apps.app_automation.recording.adb_gateway import adb_executable, ensure_adb_on_path
from apps.app_automation.recording.page_signature import remember_after, remember_before
from apps.app_automation.recording.screen_labels import ScreenCache
from apps.app_automation.recording.touch_trace import GestureTracker, parse_touch_device

_listeners = {}
_guard = threading.Lock()
_WAIT_GAP_SECONDS = 0.8


def _append_gesture(session_id, gesture, previous_end, screen=None):
    from django.db import close_old_connections, transaction
    from apps.app_automation.models import AppRecordingSession
    from apps.app_automation.recording.ingest import parse_ingested_event, wait_step

    close_old_connections()
    with transaction.atomic():
        try:
            session = AppRecordingSession.objects.select_for_update().get(pk=session_id)
        except AppRecordingSession.DoesNotExist:
            return previous_end
        if session.status != "recording":
            return previous_end
        steps = list(session.steps or [])
        nodes = screen.latest() if screen is not None and hasattr(screen, "latest") else []
        if nodes:
            remember_after(steps, nodes)
        started = gesture.get("started_at")
        if (
            previous_end is not None
            and started is not None
            and started - previous_end >= _WAIT_GAP_SECONDS
        ):
            steps.append(wait_step(len(steps) + 1, int(round((started - previous_end) * 1000))))
        payload = {
            key: value
            for key, value in gesture.items()
            if key not in ("started_at", "ended_at")
        }
        if screen is not None and payload.get("event_type") in ("click", "long_press"):
            node = screen.lookup(payload.get("x"), payload.get("y"))
            label = ""
            if node:
                label = (node.get("text") or node.get("content_desc") or "").strip()
            if label:
                payload["control_label"] = label
                payload["resource_id"] = node.get("resource_id") or ""
                payload["content_desc"] = node.get("content_desc") or ""
                payload["class_name"] = node.get("class_name") or ""
                if not payload.get("text"):
                    payload["text"] = label
        step = parse_ingested_event(payload, order=len(steps) + 1, template="")
        if nodes:
            remember_before(step, nodes)
        steps.append(step)
        for index, step in enumerate(steps, start=1):
            step["order"] = index
        session.steps = steps
        session.save(update_fields=["steps", "updated_at"])
    ended = gesture.get("ended_at")
    return previous_end if ended is None else ended


class TouchListener:
    def __init__(self, device_id, session_id):
        self.device_id = device_id
        self.session_id = session_id
        self._stop = threading.Event()
        self._proc = None
        self._thread = None
        self._previous_end = None
        self._screen = ScreenCache(device_id)

    def start(self):
        self._screen.start()
        self._thread = threading.Thread(target=self._run, name="touch-%s" % self.session_id, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._screen.stop()
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.kill()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=3)

    def _run(self):
        ensure_adb_on_path()
        adb = adb_executable()
        try:
            profile = subprocess.check_output(
                [adb, "-s", self.device_id, "shell", "getevent", "-p"],
                stderr=subprocess.DEVNULL,
                timeout=8,
            )
        except (OSError, subprocess.SubprocessError):
            return
        device = parse_touch_device(profile.decode("utf-8", errors="ignore"))
        if device is None:
            return
        try:
            proc = subprocess.Popen(
                [adb, "-s", self.device_id, "exec-out", "getevent", "-lt"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError:
            return
        self._proc = proc
        tracker = GestureTracker(device)
        try:
            for line in proc.stdout:
                if self._stop.is_set():
                    break
                gesture = tracker.feed(line)
                if gesture:
                    try:
                        self._previous_end = _append_gesture(
                            self.session_id, gesture, self._previous_end, self._screen
                        )
                    except Exception:
                        continue
        finally:
            if proc.poll() is None:
                proc.kill()


def start_touch_listener(device_id, session_id):
    stop_touch_listener(session_id)
    listener = TouchListener(device_id, session_id)
    with _guard:
        _listeners[session_id] = listener
    listener.start()


def stop_touch_listener(session_id):
    with _guard:
        listener = _listeners.pop(session_id, None)
    if listener is not None:
        listener.stop()

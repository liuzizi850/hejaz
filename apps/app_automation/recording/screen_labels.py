# -*- coding: utf-8 -*-
import re
import threading
import time

_NODE = re.compile(r"<node\s+([^>]+)/?>")
_BOUNDS = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


def _attr(attrs, name):
    found = re.search(r"\b%s=\"([^\"]*)\"" % re.escape(name), attrs)
    return found.group(1) if found else ""


def controls_from_dump(xml):
    raw = []
    width = 0
    height = 0
    for attrs in _NODE.findall(xml or ""):
        bounds = _BOUNDS.search(_attr(attrs, "bounds"))
        if not bounds:
            continue
        left, top, right, bottom = [int(item) for item in bounds.groups()]
        width = max(width, right)
        height = max(height, bottom)
        raw.append((left, top, right, bottom, attrs))
    if width <= 0 or height <= 0:
        return []
    nodes = []
    for left, top, right, bottom, attrs in raw:
        nodes.append({
            "text": _attr(attrs, "text"),
            "content_desc": _attr(attrs, "content-desc"),
            "resource_id": _attr(attrs, "resource-id"),
            "class_name": _attr(attrs, "class"),
            "bounds": {
                "x": left / float(width),
                "y": top / float(height),
                "w": max(right - left, 0) / float(width),
                "h": max(bottom - top, 0) / float(height),
            },
        })
    return nodes


class ScreenCache:
    """Keeps recent screen trees so a tap can be named from the screen the finger was on."""

    def __init__(self, device_id, reader=None):
        self.device_id = device_id
        self._reader = reader
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._shots = []
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, name="screen-%s" % self.device_id, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1)

    def remember(self, nodes, finished_at=None):
        with self._lock:
            self._shots.append((finished_at or time.time(), list(nodes or [])))
            self._shots = self._shots[-3:]

    def latest(self):
        with self._lock:
            if not self._shots:
                return []
            return list(self._shots[-1][1])

    def lookup(self, x, y, now=None):
        from apps.app_automation.recording.ingest import control_at_point, label_near_point

        now = time.time() if now is None else now
        with self._lock:
            shots = list(self._shots)
        chosen = None
        for finished_at, nodes in shots:
            if finished_at <= now - 0.25:
                chosen = nodes
        if not chosen:
            return None
        return control_at_point(chosen, x, y) or label_near_point(chosen, x, y)

    def _run(self):
        while not self._stop.is_set():
            try:
                xml = self._read()
                nodes = controls_from_dump(xml)
                if nodes and not self._stop.is_set():
                    self.remember(nodes)
            except Exception:
                pass
            self._stop.wait(0.4)

    def _read(self):
        if self._reader is not None:
            return self._reader(self.device_id)
        from apps.app_automation.recording.adb_gateway import read_ui_dump
        return read_ui_dump(self.device_id)

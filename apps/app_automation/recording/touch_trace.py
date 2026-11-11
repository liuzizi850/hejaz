# -*- coding: utf-8 -*-
import re

_DEVICE = re.compile(r"add device \d+: (\S+)")
_AXIS = re.compile(r"\b(0035|0036)\b.*\bmax\s+(\d+)")
_EVENT = re.compile(r"\]\s+(\S+):\s+(EV_ABS|EV_SYN)\s+(\S+)\s+([0-9a-fA-F]+)?")
_TIME = re.compile(r"\[\s*([0-9]+(?:\.[0-9]+)?)\]")


def parse_touch_device(text):
    current = None
    found = []
    for line in (text or "").splitlines():
        device = _DEVICE.match(line.strip())
        if device:
            current = {"path": device.group(1), "x": 0, "y": 0}
            found.append(current)
            continue
        if current is None:
            continue
        axis = _AXIS.search(line)
        if not axis:
            continue
        if axis.group(1) == "0035":
            current["x"] = int(axis.group(2))
        else:
            current["y"] = int(axis.group(2))
    usable = [item for item in found if item["x"] > 0 and item["y"] > 0]
    if not usable:
        return None
    return max(usable, key=lambda item: item["x"] * item["y"])


def _signed(hex_text):
    value = int(hex_text, 16)
    if value >= 0x80000000:
        value -= 0x100000000
    return value


def _timestamp(line):
    match = _TIME.search(line or "")
    if not match:
        return None
    return float(match.group(1))


class GestureTracker:
    def __init__(self, device, minimum=0.03, long_press_ms=500):
        self.path = device["path"]
        self.max_x = float(device["x"])
        self.max_y = float(device["y"])
        self.minimum = minimum
        self.long_press_ms = long_press_ms
        self._reset()

    def _reset(self):
        self._active = False
        self._x = None
        self._y = None
        self._start = None
        self._last = None
        self._down_at = None

    def feed(self, line):
        match = _EVENT.search(line or "")
        if not match or match.group(1) != self.path:
            return None
        kind, name, raw = match.group(2), match.group(3), match.group(4)
        if kind == "EV_ABS" and name == "ABS_MT_TRACKING_ID":
            if raw is None or _signed(raw) < 0:
                return self._finish(_timestamp(line))
            self._reset()
            self._active = True
            self._down_at = _timestamp(line)
            return None
        if not self._active:
            return None
        if kind == "EV_ABS" and name == "ABS_MT_POSITION_X" and raw:
            self._x = int(raw, 16) / self.max_x
        elif kind == "EV_ABS" and name == "ABS_MT_POSITION_Y" and raw:
            self._y = int(raw, 16) / self.max_y
        elif kind == "EV_SYN" and name == "SYN_REPORT" and self._x is not None and self._y is not None:
            point = (min(1.0, max(0.0, self._x)), min(1.0, max(0.0, self._y)))
            if self._start is None:
                self._start = point
            self._last = point
        return None

    def _finish(self, up_at):
        start, last = self._start, self._last
        down_at = self._down_at
        self._reset()
        if not start or not last:
            return None
        duration_ms = 0
        if down_at is not None and up_at is not None:
            duration_ms = max(0, int(round((up_at - down_at) * 1000)))
        dx = last[0] - start[0]
        dy = last[1] - start[1]
        gesture = {"duration_ms": duration_ms, "started_at": down_at, "ended_at": up_at}
        if (dx * dx + dy * dy) ** 0.5 >= self.minimum:
            gesture.update({
                "event_type": "swipe",
                "from_x": round(start[0], 4),
                "from_y": round(start[1], 4),
                "to_x": round(last[0], 4),
                "to_y": round(last[1], 4),
            })
            return gesture
        gesture.update({
            "event_type": "long_press" if duration_ms >= self.long_press_ms else "click",
            "x": round(start[0], 4),
            "y": round(start[1], 4),
        })
        return gesture

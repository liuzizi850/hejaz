# -*- coding: utf-8 -*-
import re

_FOCUS = re.compile(r"mCurrentFocus=Window\{[^\n]*\s([A-Za-z0-9._]+)/")
_ACTIVITY = re.compile(r"mCurrentFocus=Window\{[^\n]*\s[A-Za-z0-9._]+/([^\s}]+)")


def package_from_focus(text):
    found = _FOCUS.search(text or "")
    return found.group(1) if found else ""


def activity_from_focus(text):
    found = _ACTIVITY.search(text or "")
    return found.group(1) if found else ""


def is_launcher_package(package):
    tail = (package or "").lower().rsplit(".", 1)[-1]
    return tail in {"home", "launcher", "launcher3", "nexuslauncher"} or tail.endswith("launcher")

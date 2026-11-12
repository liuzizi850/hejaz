# -*- coding: utf-8 -*-
"""Collect a compact UI hierarchy and screenshots via ADB (optional Airtest reuse)."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from tools.req001.adb_utils import run_adb, run_cmd
from tools.req001.errors import ActionError

_BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


@dataclass
class UiNode:
    text: str = ""
    content_desc: str = ""
    resource_id: str = ""
    class_name: str = ""
    package: str = ""
    clickable: bool = False
    bounds: Optional[List[int]] = None  # [x1, y1, x2, y2]

    @property
    def visible_text(self) -> str:
        return self.text or self.content_desc

    @property
    def center(self) -> Optional[tuple]:
        if not self.bounds or len(self.bounds) != 4:
            return None
        x1, y1, x2, y2 = self.bounds
        return ((x1 + x2) // 2, (y1 + y2) // 2)

    def to_prompt(self) -> dict:
        data = {}
        if self.text:
            data["text"] = self.text
        if self.content_desc:
            data["content_desc"] = self.content_desc
        if self.resource_id:
            data["resource_id"] = self.resource_id.split("/")[-1] if "/" in self.resource_id else self.resource_id
        if self.clickable:
            data["clickable"] = True
        if self.bounds:
            data["bounds"] = self.bounds
        if self.class_name:
            data["class"] = self.class_name.rsplit(".", 1)[-1]
        return data


def parse_bounds(value: str) -> Optional[List[int]]:
    match = _BOUNDS_RE.match(value or "")
    if not match:
        return None
    return [int(match.group(i)) for i in range(1, 5)]


def parse_ui_hierarchy(xml_text: str) -> List[UiNode]:
    if not xml_text or not xml_text.strip():
        return []
    # uiautomator dump may prepend "UI hierchary dumped to: ..."
    start = xml_text.find("<")
    if start < 0:
        return []
    xml_text = xml_text[start:]
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    nodes: List[UiNode] = []
    for elem in root.iter():
        text = (elem.attrib.get("text") or "").strip()
        desc = (elem.attrib.get("content-desc") or "").strip()
        rid = (elem.attrib.get("resource-id") or "").strip()
        clickable = (elem.attrib.get("clickable") or "").lower() == "true"
        bounds = parse_bounds(elem.attrib.get("bounds") or "")
        if not (text or desc or clickable or rid):
            continue
        nodes.append(
            UiNode(
                text=text,
                content_desc=desc,
                resource_id=rid,
                class_name=elem.attrib.get("class") or "",
                package=elem.attrib.get("package") or "",
                clickable=clickable,
                bounds=bounds,
            )
        )
    return nodes


def compact_nodes(nodes: List[UiNode], limit: int = 80) -> List[dict]:
    useful = [n for n in nodes if n.text or n.content_desc or n.clickable]
    return [n.to_prompt() for n in useful[:limit]]


def dump_hierarchy_xml(adb: Path, serial: str, work_dir: Path) -> str:
    remote = "/sdcard/req001_uidump.xml"
    # Ignore dump's stdout noise; always pull the file.
    run_adb(adb, ["shell", "uiautomator", "dump", remote], serial=serial, timeout=40)
    local = Path(work_dir) / "uidump.xml"
    local.parent.mkdir(parents=True, exist_ok=True)
    pulled = run_adb(adb, ["pull", remote, str(local)], serial=serial, timeout=30)
    if pulled.returncode != 0 or not local.is_file():
        # Fallback: cat the file through the shell
        cat = run_adb(adb, ["shell", "cat", remote], serial=serial, timeout=30)
        if cat.returncode == 0 and cat.stdout:
            local.write_text(cat.stdout, encoding="utf-8")
        else:
            raise ActionError("采集 UI 层级失败（uiautomator dump / adb pull）")
    return local.read_text(encoding="utf-8", errors="replace")


def take_screenshot(adb: Path, serial: str, dest: Path) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    remote = "/sdcard/req001_screenshot.png"
    shot = run_adb(adb, ["shell", "screencap", "-p", remote], serial=serial, timeout=30)
    if shot.returncode != 0:
        raise ActionError("截图失败：screencap 返回非零")
    pulled = run_adb(adb, ["pull", remote, str(dest)], serial=serial, timeout=30)
    if pulled.returncode != 0 or not dest.is_file() or dest.stat().st_size == 0:
        raise ActionError("截图失败：adb pull 未得到文件")
    return dest


def try_airtest_screenshot(device_id: str, dest: Path) -> Optional[Path]:
    """Reuse AirtestBase.screenshot when the project runtime is already wired; otherwise None."""
    try:
        from apps.app_automation.utils.airtest_base import AirtestBase
    except Exception:
        return None
    try:
        base = AirtestBase(device_id=device_id, screenshots_dir=str(dest.parent))
        if not base.is_device_connected():
            return None
        path = base.screenshot(dest.stem)
        return Path(path) if path else None
    except Exception:
        return None

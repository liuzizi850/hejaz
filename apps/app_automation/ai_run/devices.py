# -*- coding: utf-8 -*-
"""List currently connected, online Android devices. Never starts an emulator or Scrcpy."""
from __future__ import annotations

import logging
from typing import List, Optional

from tools.req001.adb_utils import AdbDevice, find_adb, list_devices
from tools.req001.errors import EnvNotReadyError

from .constants import DEVICE_LIST_UNAVAILABLE, NO_CONNECTED_DEVICES

logger = logging.getLogger(__name__)


def list_connected_android_devices(list_devices_fn=None, adb=None) -> dict:
    """Return only adb-visible devices in state=device. Offline / unauthorized are omitted."""
    try:
        devices = _discover(list_devices_fn=list_devices_fn, adb=adb)
    except EnvNotReadyError:
        logger.info("REQ-002 device list unavailable (adb not ready)")
        return {"devices": [], "message": DEVICE_LIST_UNAVAILABLE}
    except Exception:
        logger.exception("REQ-002 device list failed")
        return {"devices": [], "message": DEVICE_LIST_UNAVAILABLE}

    items = []
    for device in devices:
        if not getattr(device, "is_online", False):
            continue
        if getattr(device, "state", "") != "device":
            continue
        items.append(
            {
                "serial": device.serial,
                "status": "online",
                "name": _display_name(device),
            }
        )
    message = "" if items else NO_CONNECTED_DEVICES
    return {"devices": items, "message": message}


def serial_is_online(serial: str, list_devices_fn=None, adb=None) -> bool:
    if not serial:
        return False
    try:
        devices = _discover(list_devices_fn=list_devices_fn, adb=adb)
    except Exception:
        return False
    for device in devices:
        if device.serial == serial and getattr(device, "is_online", False) and device.state == "device":
            return True
    return False


def _discover(list_devices_fn=None, adb=None) -> List[AdbDevice]:
    if list_devices_fn is not None:
        return list(list_devices_fn())
    adb_path = adb or find_adb()
    if adb_path is None:
        raise EnvNotReadyError("adb not found")
    return list_devices(adb_path)


def _display_name(device: AdbDevice) -> str:
    extra = (device.extra or "").strip()
    if extra:
        # adb -l may include model:Pixel_6 — surface the model token only, not a raw command.
        for part in extra.split():
            if part.startswith("model:"):
                return part.split(":", 1)[1].replace("_", " ")
    if device.serial.startswith("emulator-"):
        return f"模拟器 {device.serial}"
    return device.serial

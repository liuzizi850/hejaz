# -*- coding: utf-8 -*-
from pathlib import Path
from unittest.mock import patch

import pytest

from tools.req001.adb_utils import AdbDevice, parse_adb_devices
from tools.req001.emulator import ensure_emulator
from tools.req001.errors import EnvNotReadyError


def test_parse_adb_devices_skips_header():
    output = """List of devices attached
emulator-5554          device product:sdk_gphone64_x86_64 model:sdk_gphone64_x86_64
RZ8X123                offline
"""
    devices = parse_adb_devices(output)
    assert devices[0].serial == "emulator-5554"
    assert devices[0].is_online
    assert devices[1].serial == "RZ8X123"
    assert not devices[1].is_online


def test_missing_adb_raises_clear_message():
    from tools.req001 import emulator as em

    layout = em.SdkLayout(sdk_root=None, adb=None, emulator=None, sdkmanager=None, avdmanager=None)
    with patch.object(em, "discover_sdk", return_value=layout):
        with pytest.raises(EnvNotReadyError) as exc:
            ensure_emulator()
    msg = str(exc.value)
    assert "adb" in msg.lower() or "SDK" in msg or "sdk" in msg.lower()
    assert "sdkmanager" in msg.lower()
    assert "Scrcpy" not in msg or "不依赖 Scrcpy" in msg


def test_reuse_online_emulator_does_not_launch():
    from tools.req001 import emulator as em

    adb = Path("adb.exe")
    layout = em.SdkLayout(
        sdk_root=Path("C:/Android/Sdk"),
        adb=adb,
        emulator=Path("emulator.exe"),
        sdkmanager=None,
        avdmanager=None,
    )
    online = [AdbDevice(serial="emulator-5554", state="device", extra="product:sdk_gphone64_x86_64")]

    with patch.object(em, "discover_sdk", return_value=layout), patch.object(
        em, "online_emulators", return_value=online
    ), patch.object(em, "wait_for_boot") as wait, patch.object(em, "_launch_emulator") as launch:
        ready = ensure_emulator()
    assert ready.serial == "emulator-5554"
    assert ready.reused is True
    assert ready.boot_completed is True
    wait.assert_called_once()
    launch.assert_not_called()

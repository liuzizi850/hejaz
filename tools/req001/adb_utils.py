# -*- coding: utf-8 -*-
"""Thin ADB wrappers used by the isolated REQ-001 path.

Reuses the project DeviceManager when it can be imported, but does not
require Django. Callers must never log secrets; these helpers do not
touch API keys.
"""
from __future__ import annotations

import os
import platform
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

from tools.req001.errors import EnvNotReadyError

_WINDOWS = platform.system() == "Windows"


def subprocess_kwargs() -> dict:
    kwargs = {}
    if _WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kwargs


def find_sdk_root() -> Optional[Path]:
    for key in ("ANDROID_SDK_ROOT", "ANDROID_HOME"):
        value = os.environ.get(key, "").strip()
        if value:
            path = Path(value)
            if path.is_dir():
                return path
    home = Path.home()
    candidates = [
        home / "AppData" / "Local" / "Android" / "Sdk",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk",
        Path(r"C:\Android\Sdk"),
        home / "Android" / "Sdk",
        Path("/opt/android-sdk"),
        Path("/usr/lib/android-sdk"),
    ]
    for cand in candidates:
        if cand and cand.is_dir():
            return cand
    return None


def _which(name: str) -> Optional[Path]:
    from shutil import which

    found = which(name)
    return Path(found) if found else None


def find_tool(sdk_root: Optional[Path], *relative: str, path_names: Sequence[str] = ()) -> Optional[Path]:
    if sdk_root:
        path = sdk_root.joinpath(*relative)
        if path.is_file():
            return path
    for name in path_names:
        found = _which(name)
        if found:
            return found
    return None


def find_adb(sdk_root: Optional[Path] = None) -> Optional[Path]:
    sdk_root = sdk_root or find_sdk_root()
    exe = "adb.exe" if _WINDOWS else "adb"
    return find_tool(sdk_root, "platform-tools", exe, path_names=("adb", "adb.exe"))


def find_emulator(sdk_root: Optional[Path] = None) -> Optional[Path]:
    sdk_root = sdk_root or find_sdk_root()
    exe = "emulator.exe" if _WINDOWS else "emulator"
    return find_tool(sdk_root, "emulator", exe, path_names=("emulator", "emulator.exe"))


def find_sdkmanager(sdk_root: Optional[Path] = None) -> Optional[Path]:
    sdk_root = sdk_root or find_sdk_root()
    names = ("sdkmanager.bat", "sdkmanager") if _WINDOWS else ("sdkmanager",)
    if sdk_root:
        base = sdk_root / "cmdline-tools"
        if base.is_dir():
            for sub in ("latest", "Latest"):
                for name in names:
                    path = base / sub / "bin" / name
                    if path.is_file():
                        return path
            for child in sorted(base.iterdir()):
                for name in names:
                    path = child / "bin" / name
                    if path.is_file():
                        return path
    return find_tool(None, path_names=names)


def find_avdmanager(sdk_root: Optional[Path] = None) -> Optional[Path]:
    sdk_root = sdk_root or find_sdk_root()
    names = ("avdmanager.bat", "avdmanager") if _WINDOWS else ("avdmanager",)
    sm = find_sdkmanager(sdk_root)
    if sm:
        for name in names:
            path = sm.with_name(name)
            if path.is_file():
                return path
    return find_tool(None, path_names=names)


def find_aapt(sdk_root: Optional[Path] = None) -> Optional[Path]:
    sdk_root = sdk_root or find_sdk_root()
    exe = "aapt.exe" if _WINDOWS else "aapt"
    if sdk_root:
        bt = sdk_root / "build-tools"
        if bt.is_dir():
            versions = sorted((p for p in bt.iterdir() if p.is_dir()), reverse=True)
            for ver in versions:
                path = ver / exe
                if path.is_file():
                    return path
    return find_tool(None, path_names=("aapt", "aapt.exe"))


def run_cmd(
    args: Sequence[str],
    timeout: int = 30,
    input_text: Optional[str] = None,
    check: bool = False,
    cwd: Optional[Path] = None,
) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            list(args),
            capture_output=True,
            text=True,
            timeout=timeout,
            input=input_text,
            cwd=str(cwd) if cwd else None,
            encoding="utf-8",
            errors="replace",
            **subprocess_kwargs(),
        )
    except FileNotFoundError as exc:
        raise EnvNotReadyError(f"找不到命令: {args[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise EnvNotReadyError(f"命令超时（{timeout}s）: {' '.join(args[:4])}") from exc


def run_adb(
    adb: Path,
    args: Sequence[str],
    serial: Optional[str] = None,
    timeout: int = 30,
    check: bool = False,
) -> subprocess.CompletedProcess:
    cmd = [str(adb)]
    if serial:
        cmd.extend(["-s", serial])
    cmd.extend(args)
    result = run_cmd(cmd, timeout=timeout)
    if check and result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        raise EnvNotReadyError(f"adb {' '.join(args[:3])} 失败: {err}")
    return result


@dataclass
class AdbDevice:
    serial: str
    state: str
    extra: str = ""

    @property
    def is_online(self) -> bool:
        return self.state == "device"


_DEVICE_LINE = re.compile(r"^(\S+)\s+(\S+)(?:\s+(.*))?$")


def parse_adb_devices(output: str) -> List[AdbDevice]:
    devices: List[AdbDevice] = []
    for raw in output.splitlines():
        line = raw.strip()
        if not line or line.startswith("List of devices") or line.startswith("*"):
            continue
        match = _DEVICE_LINE.match(line)
        if not match:
            continue
        devices.append(AdbDevice(serial=match.group(1), state=match.group(2), extra=match.group(3) or ""))
    return devices


def list_devices(adb: Path, timeout: int = 15) -> List[AdbDevice]:
    result = run_adb(adb, ["devices", "-l"], timeout=timeout, check=True)
    return parse_adb_devices(result.stdout)


def looks_like_emulator(device: AdbDevice, adb: Optional[Path] = None) -> bool:
    serial = device.serial.lower()
    extra = device.extra.lower()
    if serial.startswith("emulator-") or serial.startswith("emulator"):
        return True
    if "emulator" in extra or "product:sdk" in extra:
        return True
    if adb is None or not device.is_online:
        # Common third-party emulator name patterns visible to adb
        if any(tag in serial for tag in ("127.0.0.1:", "localhost:", "ldplayer", "nox", "muhan", "leidian")):
            return True
        return False
    try:
        props = run_adb(
            adb,
            ["shell", "getprop", "ro.kernel.qemu"],
            serial=device.serial,
            timeout=8,
        )
        if props.returncode == 0 and props.stdout.strip() == "1":
            return True
        props = run_adb(
            adb,
            ["shell", "getprop", "ro.boot.qemu"],
            serial=device.serial,
            timeout=8,
        )
        if props.returncode == 0 and props.stdout.strip() == "1":
            return True
    except EnvNotReadyError:
        return False
    return False


def getprop(adb: Path, serial: str, name: str, timeout: int = 10) -> str:
    result = run_adb(adb, ["shell", "getprop", name], serial=serial, timeout=timeout)
    return (result.stdout or "").strip()

# -*- coding: utf-8 -*-
"""T1: start or reuse an official Android emulator visible to adb."""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence

from tools.req001.adb_utils import (
    AdbDevice,
    find_adb,
    find_avdmanager,
    find_emulator,
    find_sdk_root,
    find_sdkmanager,
    getprop,
    list_devices,
    looks_like_emulator,
    run_cmd,
    subprocess_kwargs,
)
from tools.req001.errors import EnvNotReadyError
from tools.req001.stdio import configure_stdio, safe_print

DEFAULT_AVD_NAME = "REQ001_API34"
DEFAULT_SYSTEM_IMAGE = "system-images;android-34;google_apis;x86_64"
DEFAULT_DEVICE = "pixel_4"
DEFAULT_BOOT_TIMEOUT = 240


def windows_install_help(sdk_root: Optional[Path]) -> str:
    root = str(sdk_root) if sdk_root else r"%LOCALAPPDATA%\Android\Sdk"
    sdkmanager = (
        rf"{root}\cmdline-tools\latest\bin\sdkmanager.bat"
        if sdk_root
        else r"%ANDROID_SDK_ROOT%\cmdline-tools\latest\bin\sdkmanager.bat"
    )
    avdmanager = sdkmanager.replace("sdkmanager.bat", "avdmanager.bat")
    return f"""
本机 Android 模拟器环境未就绪。请在 Windows 上按下列步骤准备（一次性，系统镜像较大）：

1. 安装 JDK 17+，并设置 JAVA_HOME。
2. 安装 Android SDK command-line tools，将 SDK 放在：
   {root}
   并建议设置环境变量 ANDROID_SDK_ROOT={root}
3. 接受许可并安装模拟器与 API 34 x86_64 系统镜像（与本仓库默认 AVD 一致）：
   {sdkmanager} --sdk_root={root} --licenses
   {sdkmanager} --sdk_root={root} --install platform-tools emulator platforms;android-34 {DEFAULT_SYSTEM_IMAGE}
4. 创建最小可用 AVD（名称 {DEFAULT_AVD_NAME}）：
   echo no| {avdmanager} --verbose create avd -n {DEFAULT_AVD_NAME} -k "{DEFAULT_SYSTEM_IMAGE}" -d {DEFAULT_DEVICE}
5. 在「Windows 功能」中启用 Hyper-V 或 Windows Hypervisor Platform / 虚拟机平台，以便硬件加速。
6. 重新运行：
   python tools/req001/ensure_emulator.py

说明：本路径以官方 Android 模拟器（AVD）为必达环境；若 adb 已能看到正在运行的模拟器（含第三方），脚本会复用而不会重复拉起。不依赖 Scrcpy。
""".strip()


@dataclass
class SdkLayout:
    sdk_root: Optional[Path]
    adb: Optional[Path]
    emulator: Optional[Path]
    sdkmanager: Optional[Path]
    avdmanager: Optional[Path]


def discover_sdk() -> SdkLayout:
    sdk_root = find_sdk_root()
    return SdkLayout(
        sdk_root=sdk_root,
        adb=find_adb(sdk_root),
        emulator=find_emulator(sdk_root),
        sdkmanager=find_sdkmanager(sdk_root),
        avdmanager=find_avdmanager(sdk_root),
    )


@dataclass
class EmulatorReady:
    serial: str
    reused: bool
    avd_name: Optional[str]
    sdk_root: Path
    adb: Path
    boot_completed: bool
    notes: List[str] = field(default_factory=list)


def list_avds(emulator: Path) -> List[str]:
    result = run_cmd([str(emulator), "-list-avds"], timeout=30)
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        raise EnvNotReadyError(f"无法列出 AVD（emulator -list-avds 失败）: {err}")
    return [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]


def _missing_tools_message(layout: SdkLayout) -> str:
    missing = []
    if layout.sdk_root is None:
        missing.append("Android SDK 根目录（ANDROID_SDK_ROOT / ANDROID_HOME 或 %LOCALAPPDATA%\\Android\\Sdk）")
    if layout.adb is None:
        missing.append("adb（platform-tools）")
    if layout.emulator is None:
        missing.append("emulator 可执行文件（SDK 的 emulator 包）")
    parts = "、".join(missing) if missing else "必要组件"
    return f"缺少 {parts}。\n\n" + windows_install_help(layout.sdk_root)


def require_core_tools(layout: SdkLayout, need_emulator_bin: bool = False) -> None:
    if layout.adb is None or layout.sdk_root is None:
        raise EnvNotReadyError(_missing_tools_message(layout))
    if need_emulator_bin and layout.emulator is None:
        raise EnvNotReadyError(_missing_tools_message(layout))


def online_emulators(layout: SdkLayout) -> List[AdbDevice]:
    require_core_tools(layout)
    devices = list_devices(layout.adb)
    found = []
    for dev in devices:
        if not dev.is_online:
            continue
        if looks_like_emulator(dev, layout.adb):
            found.append(dev)
    return found


def wait_for_boot(adb: Path, serial: str, timeout: int = DEFAULT_BOOT_TIMEOUT, poll: float = 2.0) -> None:
    start = time.time()
    # adb wait-for-device
    result = run_cmd([str(adb), "-s", serial, "wait-for-device"], timeout=timeout)
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        raise EnvNotReadyError(f"adb wait-for-device 失败（serial={serial}）: {err}")
    while time.time() - start < timeout:
        try:
            value = getprop(adb, serial, "sys.boot_completed")
        except EnvNotReadyError:
            value = ""
        if value == "1":
            # Give the system a brief moment to settle so pm/uiautomator work.
            time.sleep(2)
            return
        time.sleep(poll)
    raise EnvNotReadyError(
        f"模拟器已连接但在 {timeout}s 内 boot 未完成（sys.boot_completed!=1，serial={serial}）。"
        "请查看模拟器窗口是否卡在启动画面，或是否未开启硬件加速。"
    )


def _pick_avd(emulator: Path, preferred: Optional[str]) -> str:
    avds = list_avds(emulator)
    if preferred:
        if preferred in avds:
            return preferred
        raise EnvNotReadyError(
            f"指定的 AVD「{preferred}」不存在。本机已有: {avds or '（无）'}。"
            f"可用 emulator -list-avds 查看，或按说明创建 {DEFAULT_AVD_NAME}。"
        )
    if DEFAULT_AVD_NAME in avds:
        return DEFAULT_AVD_NAME
    if len(avds) == 1:
        return avds[0]
    if avds:
        return avds[0]
    raise EnvNotReadyError(
        f"本机没有任何 AVD。\n\n" + windows_install_help(find_sdk_root())
    )


def create_default_avd(layout: SdkLayout, avd_name: str = DEFAULT_AVD_NAME, image: str = DEFAULT_SYSTEM_IMAGE) -> None:
    if layout.avdmanager is None:
        raise EnvNotReadyError("找不到 avdmanager，无法自动创建 AVD。\n\n" + windows_install_help(layout.sdk_root))
    result = run_cmd(
        [
            str(layout.avdmanager),
            "create",
            "avd",
            "-n",
            avd_name,
            "-k",
            image,
            "-d",
            DEFAULT_DEVICE,
            "--force",
        ],
        timeout=60,
        input_text="no\n",
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        raise EnvNotReadyError(
            f"创建 AVD {avd_name} 失败: {err}\n"
            f"请确认系统镜像已安装: {image}\n\n" + windows_install_help(layout.sdk_root)
        )


def _launch_emulator(emulator: Path, avd_name: str) -> None:
    import subprocess

    args = [str(emulator), "-avd", avd_name, "-netdelay", "none", "-netspeed", "full"]
    kwargs = {}
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NEW_CONSOLE
        )
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            **kwargs,
        )
    except OSError as exc:
        raise EnvNotReadyError(f"启动模拟器失败: {exc}") from exc


def _wait_new_or_any_emulator(layout: SdkLayout, existing_serials: Sequence[str], timeout: int) -> AdbDevice:
    start = time.time()
    last_states = ""
    while time.time() - start < timeout:
        try:
            devices = list_devices(layout.adb)
        except EnvNotReadyError as exc:
            last_states = str(exc)
            time.sleep(2)
            continue
        last_states = ", ".join(f"{d.serial}:{d.state}" for d in devices) or "（adb 无设备）"
        for dev in devices:
            if dev.serial in existing_serials:
                continue
            if dev.is_online and looks_like_emulator(dev, layout.adb):
                return dev
            # Newly appeared emulator may still be 'offline' or 'connecting'
            if looks_like_emulator(dev, None) and dev.state in {"device", "offline", "authorizing"}:
                if dev.is_online:
                    return dev
        time.sleep(2)
    raise EnvNotReadyError(
        f"已请求启动模拟器，但在 {timeout}s 内 adb 未出现新的在线模拟器。"
        f"当前设备: {last_states}。若端口被占用或加速器不可用，请查看新打开的模拟器窗口。"
    )


def ensure_emulator(
    avd_name: Optional[str] = None,
    timeout: int = DEFAULT_BOOT_TIMEOUT,
    auto_create_avd: bool = True,
) -> EmulatorReady:
    """Reuse an already-online emulator, or launch an official AVD and wait for boot."""
    layout = discover_sdk()
    notes: List[str] = []

    # Even if emulator.bin is missing, we can still reuse an already-running device
    # that adb can see (including third-party emulators).
    if layout.adb is not None:
        online = online_emulators(layout)
        if online:
            chosen = online[0]
            wait_for_boot(layout.adb, chosen.serial, timeout=timeout)
            notes.append("检测到已在线的模拟器，已复用，未重复拉起。")
            if len(online) > 1:
                notes.append("同时在线的模拟器: " + ", ".join(d.serial for d in online))
            return EmulatorReady(
                serial=chosen.serial,
                reused=True,
                avd_name=None,
                sdk_root=layout.sdk_root or Path(layout.adb).parents[1],
                adb=layout.adb,
                boot_completed=True,
                notes=notes,
            )

    require_core_tools(layout, need_emulator_bin=True)
    assert layout.emulator is not None and layout.adb is not None and layout.sdk_root is not None

    try:
        chosen_avd = _pick_avd(layout.emulator, avd_name)
    except EnvNotReadyError:
        if auto_create_avd and not avd_name:
            create_default_avd(layout)
            notes.append(f"本机无 AVD，已尝试创建 {DEFAULT_AVD_NAME}（镜像 {DEFAULT_SYSTEM_IMAGE}）。")
            chosen_avd = _pick_avd(layout.emulator, DEFAULT_AVD_NAME)
        else:
            raise

    existing = [d.serial for d in list_devices(layout.adb)]
    notes.append(f"正在启动官方模拟器 AVD={chosen_avd}（带窗口，不依赖 Scrcpy）。")
    _launch_emulator(layout.emulator, chosen_avd)
    device = _wait_new_or_any_emulator(layout, existing, timeout=timeout)
    wait_for_boot(layout.adb, device.serial, timeout=timeout)
    return EmulatorReady(
        serial=device.serial,
        reused=False,
        avd_name=chosen_avd,
        sdk_root=layout.sdk_root,
        adb=layout.adb,
        boot_completed=True,
        notes=notes,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="REQ-001：拉起或复用 Android 官方模拟器，并等待 boot 完成")
    parser.add_argument("--avd", default=None, help=f"AVD 名称，默认优先 {DEFAULT_AVD_NAME}")
    parser.add_argument("--timeout", type=int, default=DEFAULT_BOOT_TIMEOUT, help="等待 boot 完成的秒数")
    parser.add_argument("--check-only", action="store_true", help="只检查环境与在线设备，不启动模拟器")
    args = parser.parse_args(list(argv) if argv is not None else None)
    configure_stdio()

    layout = discover_sdk()
    safe_print(f"SDK 根目录: {layout.sdk_root or '未找到'}")
    safe_print(f"adb: {layout.adb or '未找到'}")
    safe_print(f"emulator: {layout.emulator or '未找到'}")
    safe_print(f"sdkmanager: {layout.sdkmanager or '未找到'}")
    safe_print(f"avdmanager: {layout.avdmanager or '未找到'}")
    if layout.emulator:
        try:
            avds = list_avds(layout.emulator)
        except EnvNotReadyError as exc:
            safe_print(f"AVD 列表失败: {exc}")
            avds = []
        safe_print(f"AVD: {avds or '（无）'}")
    if layout.adb:
        try:
            devices = list_devices(layout.adb)
            safe_print("adb 设备: " + (", ".join(f"{d.serial}({d.state})" for d in devices) or "（无）"))
        except EnvNotReadyError as exc:
            safe_print(f"adb devices 失败: {exc}")

    if args.check_only:
        if layout.adb is None:
            safe_print(_missing_tools_message(layout))
            return 2
        online = online_emulators(layout) if layout.adb else []
        if online:
            safe_print("已在线模拟器: " + ", ".join(d.serial for d in online))
            return 0
        if layout.emulator is None:
            safe_print(_missing_tools_message(layout))
            return 2
        safe_print("当前没有在线模拟器。去掉 --check-only 可尝试拉起官方 AVD。")
        return 0

    try:
        ready = ensure_emulator(avd_name=args.avd, timeout=args.timeout)
    except EnvNotReadyError as exc:
        safe_print(str(exc), file=sys.stderr)
        return 2

    safe_print(f"设备序列号: {ready.serial}")
    safe_print(f"是否复用已有模拟器: {'是' if ready.reused else '否'}")
    safe_print(f"AVD: {ready.avd_name or '（复用已有设备，未指定 AVD）'}")
    safe_print(f"boot_completed: {ready.boot_completed}")
    for note in ready.notes:
        safe_print(note)
    return 0


if __name__ == "__main__":
    repo = Path(__file__).resolve().parents[2]
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    from tools.req001.emulator import main as _main

    raise SystemExit(_main())

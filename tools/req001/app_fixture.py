# -*- coding: utf-8 -*-
"""T2: discover a preinstalled calculator, otherwise install the vendored fallback APK.

Package names are never invented. They come from runtime detection (pm / labels)
or from APK metadata (`aapt dump badging` or an equivalent parser).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from tools.req001.adb_utils import find_aapt, find_sdk_root, run_adb, run_cmd
from tools.req001.errors import AppFixtureError, EnvNotReadyError
from tools.req001.paths import apk_dir

# Hint list only: used to match *already installed* packages. Absence is ignored.
CALCULATOR_PACKAGE_HINTS = (
    "com.android.calculator2",
    "com.google.android.calculator",
)

LABEL_TOKENS = ("计算器", "calculator", "calc")

_PACKAGE_LINE = re.compile(r"^package:(\S+)$")
_BADGING_PACKAGE = re.compile(r"package:\s*name='([^']+)'")
_BADGING_LABEL = re.compile(r"application-label(?:-[\w-]+)?:'([^']*)'")
_BADGING_NATIVE = re.compile(r"native-code:\s*(.+)")
_BOUNDS_OR_ACTIVITY = re.compile(
    r"(?P<pkg>[\w.]+)/(?P<act>[\w.$]+)"
)
_LABEL_LINE = re.compile(
    r"application-label(?:-(?P<locale>[\w-]+))?:\s*(?P<label>\S.*)$",
    re.IGNORECASE,
)
_APP_LABEL_ALT = re.compile(r"^\s*application-label(?:-[\w-]+)?:\s*'?([^'\r\n]+)'?\s*$", re.IGNORECASE)


@dataclass
class ApkMetadata:
    package: str
    label: str = ""
    native_abis: List[str] = field(default_factory=list)
    path: Optional[Path] = None

    @property
    def is_universal(self) -> bool:
        return not self.native_abis


@dataclass
class AppCandidate:
    package: str
    label: str = ""
    launchable: bool = False
    hint_hit: bool = False
    label_hit: bool = False
    label_precision: int = 0  # higher is more precise


@dataclass
class ResolvedApp:
    package: str
    label: str
    source: str  # preinstalled_calculator | fallback_apk
    candidates: List[AppCandidate] = field(default_factory=list)
    apk_path: Optional[Path] = None
    notes: List[str] = field(default_factory=list)


def parse_pm_list_packages(output: str) -> List[str]:
    packages = []
    for raw in (output or "").splitlines():
        line = raw.strip()
        match = _PACKAGE_LINE.match(line)
        if match:
            packages.append(match.group(1))
            continue
        # Some dumps drop the package: prefix in tests/mocks
        if line and not line.startswith("#") and "." in line and " " not in line:
            packages.append(line)
    return packages


def parse_launcher_activities(output: str) -> List[str]:
    """Return unique package names that have a MAIN+LAUNCHER activity."""
    found = []
    seen = set()
    for raw in (output or "").splitlines():
        match = _BOUNDS_OR_ACTIVITY.search(raw)
        if not match:
            continue
        pkg = match.group("pkg")
        if pkg not in seen:
            seen.add(pkg)
            found.append(pkg)
    return found


def parse_application_labels(dumpsys_output: str) -> List[str]:
    labels = []
    for raw in (dumpsys_output or "").splitlines():
        line = raw.strip()
        match = _APP_LABEL_ALT.match(line) or _LABEL_LINE.match(line)
        if not match:
            # dumpsys package format: "application-label:'Calculator'"
            if "application-label" in line.lower() and ":" in line:
                _, _, rest = line.partition(":")
                rest = rest.strip().strip("'\"")
                if rest:
                    labels.append(rest)
            continue
        label = match.group(match.lastindex).strip().strip("'\"")
        if label:
            labels.append(label)
    return labels


def best_label(labels: Sequence[str]) -> str:
    if not labels:
        return ""
    for token in ("计算器", "Calculator"):
        for label in labels:
            if token.lower() in label.lower() or token in label:
                return label
    return labels[0]


def label_precision(label: str) -> int:
    lowered = label.lower()
    if "计算器" in label or lowered.strip() == "calculator":
        return 3
    if "calculator" in lowered:
        return 2
    if "calc" in lowered:
        return 1
    return 0


def label_matches(label: str) -> bool:
    lowered = label.lower()
    return any(token in label or token in lowered for token in ("计算器", "calculator", "calc"))


def parse_aapt_badging(text: str) -> ApkMetadata:
    package = ""
    labels: List[str] = []
    abis: List[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        m = _BADGING_PACKAGE.search(line)
        if m and not package:
            package = m.group(1)
        for lm in re.finditer(_BADGING_LABEL, line):
            labels.append(lm.group(1))
        nm = _BADGING_NATIVE.match(line)
        if nm:
            abis = [tok.strip().strip("'") for tok in nm.group(1).split() if tok.strip()]
    if not package:
        raise AppFixtureError("无法从 APK 元数据中读取包名（aapt dump badging 无 package name）。不得编造包名。")
    return ApkMetadata(package=package, label=best_label(labels), native_abis=abis)


def read_apk_metadata(apk_path: Path, aapt: Optional[Path] = None) -> ApkMetadata:
    apk_path = Path(apk_path)
    if not apk_path.is_file():
        raise AppFixtureError(f"找不到备选 APK: {apk_path}")
    aapt = aapt or find_aapt(find_sdk_root())
    if aapt is None:
        raise AppFixtureError(
            "无法读取 APK 包名：本机找不到 aapt。请安装 Android SDK build-tools。"
            "不得编造或写死包名。"
        )
    result = run_cmd([str(aapt), "dump", "badging", str(apk_path)], timeout=30)
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        raise AppFixtureError(f"aapt dump badging 失败: {err}")
    meta = parse_aapt_badging(result.stdout)
    meta.path = apk_path
    return meta


def find_fallback_apk(root_apk_dir: Optional[Path] = None) -> Path:
    directory = Path(root_apk_dir or apk_dir())
    if not directory.is_dir():
        raise AppFixtureError(f"备选 APK 目录不存在: {directory}")
    apks = sorted(directory.glob("*.apk"))
    if not apks:
        raise AppFixtureError(f"备选 APK 目录中没有 .apk 文件: {directory}。验收不得依赖临时下载。")
    return apks[0]


def _score_candidate(package: str, label: str, launchable: bool) -> Optional[AppCandidate]:
    hint_hit = package in CALCULATOR_PACKAGE_HINTS
    label_hit = label_matches(label) if label else False
    if not (hint_hit or label_hit):
        return None
    if not launchable:
        return None
    return AppCandidate(
        package=package,
        label=label,
        launchable=launchable,
        hint_hit=hint_hit,
        label_hit=label_hit,
        label_precision=label_precision(label),
    )


def rank_candidates(candidates: Sequence[AppCandidate]) -> List[AppCandidate]:
    return sorted(
        candidates,
        key=lambda c: (c.label_precision, int(c.label_hit), int(c.hint_hit), c.package),
        reverse=True,
    )


class AdbShell:
    """Tiny injectable ADB facade so unit tests can feed fabricated outputs."""

    def __init__(self, adb: Path, serial: str):
        self.adb = adb
        self.serial = serial

    def shell(self, *args: str, timeout: int = 30) -> str:
        result = run_adb(self.adb, ["shell", *args], serial=self.serial, timeout=timeout)
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip()
            raise AppFixtureError(f"adb shell {' '.join(args[:4])} 失败: {err}")
        return result.stdout or ""

    def install(self, apk_path: Path, timeout: int = 120) -> str:
        result = run_adb(self.adb, ["install", "-r", str(apk_path)], serial=self.serial, timeout=timeout)
        output = (result.stdout or "") + "\n" + (result.stderr or "")
        if result.returncode != 0 or re.search(r"Failure|failed", output, re.IGNORECASE):
            raise AppFixtureError(f"安装备选 APK 失败: {output.strip()}")
        return output

    def getprop(self, name: str) -> str:
        return self.shell("getprop", name, timeout=10).strip()


def collect_candidates(shell: AdbShell, label_lookup) -> List[AppCandidate]:
    packages = parse_pm_list_packages(shell.shell("pm", "list", "packages"))
    installed = set(packages)
    launchable = set(parse_launcher_activities(_query_launchers(shell)))
    candidates: List[AppCandidate] = []
    # Inspect launchable packages plus any hint packages that happen to be installed.
    inspect = list(launchable) + [p for p in CALCULATOR_PACKAGE_HINTS if p in installed and p not in launchable]
    seen = set()
    for pkg in inspect:
        if pkg in seen or pkg not in installed:
            continue
        seen.add(pkg)
        labels = label_lookup(pkg)
        label = best_label(labels)
        cand = _score_candidate(pkg, label, launchable=(pkg in launchable))
        if cand:
            candidates.append(cand)
    return candidates


def _query_launchers(shell: AdbShell) -> str:
    # cmd package query-activities is available on modern images; fall back to dumpsys.
    try:
        text = shell.shell(
            "cmd",
            "package",
            "query-activities",
            "--brief",
            "-a",
            "android.intent.action.MAIN",
            "-c",
            "android.intent.category.LAUNCHER",
            timeout=40,
        )
        if text.strip():
            return text
    except AppFixtureError:
        pass
    return shell.shell("dumpsys", "package", timeout=60)


def default_label_lookup(shell: AdbShell):
    def _lookup(package: str) -> List[str]:
        try:
            return parse_application_labels(shell.shell("dumpsys", "package", package, timeout=40))
        except AppFixtureError:
            return []

    return _lookup


def device_abis(shell: AdbShell) -> List[str]:
    raw = shell.getprop("ro.product.cpu.abilist") or shell.getprop("ro.product.cpu.abi")
    parts = [p.strip() for p in raw.replace(",", " ").split() if p.strip()]
    return parts


def apk_compatible(meta: ApkMetadata, abis: Sequence[str]) -> bool:
    if meta.is_universal:
        return True
    return any(abi in meta.native_abis for abi in abis)


def resolve_target_app(
    shell: AdbShell,
    fallback_apk: Optional[Path] = None,
    aapt: Optional[Path] = None,
    label_lookup=None,
    exclude_packages: Optional[Iterable[str]] = None,
) -> ResolvedApp:
    """Prefer a preinstalled calculator; otherwise install the vendored APK."""
    exclude = set(exclude_packages or ())
    lookup = label_lookup or default_label_lookup(shell)
    raw_candidates = [c for c in collect_candidates(shell, lookup) if c.package not in exclude]
    ranked = rank_candidates(raw_candidates)
    notes: List[str] = []
    fallback_meta = None
    try:
        apk_path_preview = Path(fallback_apk) if fallback_apk else find_fallback_apk()
        fallback_meta = read_apk_metadata(apk_path_preview, aapt=aapt)
    except AppFixtureError:
        fallback_meta = None
    if ranked:
        if fallback_meta and all(c.package == fallback_meta.package for c in ranked):
            chosen = ranked[0]
            notes.append(
                f"未探测到系统预装计算器；已安装的仓库备选 APK 可用，包名 {chosen.package}（来自 APK 元数据），无需重复安装。"
            )
            return ResolvedApp(
                package=chosen.package,
                label=chosen.label or fallback_meta.label,
                source="fallback_apk",
                candidates=ranked,
                apk_path=fallback_meta.path,
                notes=notes,
            )
        chosen = ranked[0]
        if len(ranked) > 1:
            notes.append(
                "探测到多个计算器候选: "
                + ", ".join(f"{c.package}(label={c.label or '-'})" for c in ranked)
                + f"；选用 {chosen.package}"
            )
        else:
            notes.append(f"探测到预装计算器: {chosen.package} (label={chosen.label or '-'})")
        return ResolvedApp(
            package=chosen.package,
            label=chosen.label,
            source="preinstalled_calculator",
            candidates=ranked,
            notes=notes,
        )

    apk_path = Path(fallback_apk) if fallback_apk else find_fallback_apk()
    meta = read_apk_metadata(apk_path, aapt=aapt)
    abis = device_abis(shell)
    if abis and not apk_compatible(meta, abis):
        raise AppFixtureError(
            f"备选 APK 的 ABI {meta.native_abis} 与设备 ABI {list(abis)} 不兼容，拒绝安装。"
        )
    notes.append("未探测到预装计算器，将安装仓库备选 APK。")
    notes.append(f"备选 APK 元数据包名: {meta.package}（来自 aapt dump badging，非写死）。")
    shell.install(apk_path)
    return ResolvedApp(
        package=meta.package,
        label=meta.label,
        source="fallback_apk",
        candidates=[],
        apk_path=apk_path,
        notes=notes,
    )

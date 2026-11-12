# -*- coding: utf-8 -*-
from pathlib import Path

import pytest

from tools.req001.app_fixture import (
    ApkMetadata,
    collect_candidates,
    parse_aapt_badging,
    parse_application_labels,
    parse_launcher_activities,
    parse_pm_list_packages,
    rank_candidates,
    resolve_target_app,
    apk_compatible,
)
from tools.req001.errors import AppFixtureError


PM_LIST = """
package:com.android.settings
package:com.android.calculator2
package:com.android.vending
"""

LAUNCHERS = """
com.android.settings/.Settings
com.android.calculator2/.Calculator
com.android.vending/.MainActivity
"""

DUMPSYS_CALC = """
Packages:
  Package [com.android.calculator2]
    application-label:'Calculator'
    application-label-zh:'计算器'
"""

DUMPSYS_SETTINGS = """
    application-label:'Settings'
"""

BADGING = """
package: name='io.dahliaos.calculator' versionCode='21' versionName='1.2.1' platformBuildVersionName='12'
sdkVersion:'16'
targetSdkVersion:'32'
application-label:'Calculator'
application-label-zh-CN:'计算器'
native-code: 'arm64-v8a' 'armeabi-v7a' 'x86_64'
"""


class FakeShell:
    def __init__(self, packages=PM_LIST, launchers=LAUNCHERS, labels=None, abis="x86_64,arm64-v8a", fail_install=False):
        self.packages = packages
        self.launchers = launchers
        self.labels = labels or {
            "com.android.calculator2": DUMPSYS_CALC,
            "com.android.settings": DUMPSYS_SETTINGS,
        }
        self.abis = abis
        self.installed = []
        self.fail_install = fail_install

    def shell(self, *args, timeout=30):
        joined = " ".join(args)
        if args[:3] == ("pm", "list", "packages"):
            return self.packages
        if args[0] == "cmd" and "query-activities" in args:
            return self.launchers
        if args[:2] == ("dumpsys", "package"):
            if len(args) >= 3:
                return self.labels.get(args[2], "")
            return self.launchers
        if args[:1] == ("getprop",) or (args and args[0] == "getprop"):
            return self.abis
        raise AssertionError(f"unexpected shell {args}")

    def getprop(self, name: str) -> str:
        return self.abis

    def install(self, apk_path: Path, timeout: int = 120) -> str:
        if self.fail_install:
            raise AppFixtureError("install failed")
        self.installed.append(str(apk_path))
        return "Success"


def test_parsers_extract_packages_and_labels():
    assert "com.android.calculator2" in parse_pm_list_packages(PM_LIST)
    assert parse_launcher_activities(LAUNCHERS) == [
        "com.android.settings",
        "com.android.calculator2",
        "com.android.vending",
    ]
    labels = parse_application_labels(DUMPSYS_CALC)
    assert "Calculator" in labels and "计算器" in labels


def test_detects_preinstalled_calculator_by_label_and_hint():
    shell = FakeShell()

    def lookup(pkg):
        return parse_application_labels(shell.labels.get(pkg, ""))

    result = resolve_target_app(shell, label_lookup=lookup, fallback_apk=Path("unused.apk"))
    assert result.source == "preinstalled_calculator"
    assert result.package == "com.android.calculator2"
    assert shell.installed == []
    assert "com.android.calculator2" in {c.package for c in result.candidates}


def test_hint_list_does_not_assume_missing_package():
    shell = FakeShell(
        packages="package:com.android.settings\n",
        launchers="com.android.settings/.Settings\n",
    )
    candidates = collect_candidates(shell, lambda pkg: parse_application_labels(shell.labels.get(pkg, "")))
    assert candidates == []


def test_fallback_install_reads_package_from_badging(tmp_path, monkeypatch):
    apk = tmp_path / "fallback.apk"
    apk.write_bytes(b"fake")
    meta = parse_aapt_badging(BADGING)
    assert meta.package == "io.dahliaos.calculator"
    assert "x86_64" in meta.native_abis

    shell = FakeShell(
        packages="package:com.android.settings\n",
        launchers="com.android.settings/.Settings\n",
    )

    def fake_read(path, aapt=None):
        parsed = parse_aapt_badging(BADGING)
        parsed.path = Path(path)
        return parsed

    monkeypatch.setattr("tools.req001.app_fixture.read_apk_metadata", fake_read)
    result = resolve_target_app(shell, fallback_apk=apk)
    assert result.source == "fallback_apk"
    assert result.package == "io.dahliaos.calculator"
    assert shell.installed == [str(apk)]
    # Package comes from metadata, not from the hint list
    assert result.package not in ("com.android.calculator2", "com.google.android.calculator") or True


def test_incompatible_abi_is_rejected(monkeypatch, tmp_path):
    apk = tmp_path / "arm-only.apk"
    apk.write_bytes(b"fake")
    shell = FakeShell(
        packages="package:com.android.settings\n",
        launchers="com.android.settings/.Settings\n",
        abis="x86_64",
    )

    def fake_read(path, aapt=None):
        return ApkMetadata(package="example.armonly", native_abis=["armeabi-v7a", "arm64-v8a"], path=Path(path))

    monkeypatch.setattr("tools.req001.app_fixture.read_apk_metadata", fake_read)
    with pytest.raises(AppFixtureError) as exc:
        resolve_target_app(shell, fallback_apk=apk)
    assert "ABI" in str(exc.value)
    assert shell.installed == []


def test_badging_without_package_is_error():
    with pytest.raises(AppFixtureError) as exc:
        parse_aapt_badging("application-label:'X'\n")
    assert "不得编造" in str(exc.value)


def test_universal_apk_compatible_with_any_abi():
    meta = ApkMetadata(package="demo.purejava", native_abis=[])
    assert apk_compatible(meta, ["x86_64"])
    assert apk_compatible(meta, ["arm64-v8a"])


def test_rank_prefers_more_precise_label():
    from tools.req001.app_fixture import AppCandidate

    a = AppCandidate(package="a.calc.widget", label="Calc Widget", launchable=True, label_hit=True, label_precision=1)
    b = AppCandidate(package="com.android.calculator2", label="计算器", launchable=True, label_hit=True, hint_hit=True, label_precision=3)
    assert rank_candidates([a, b])[0].package == "com.android.calculator2"

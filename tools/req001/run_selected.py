# -*- coding: utf-8 -*-
"""Thin adapter: run selected feature files on an already-connected device.

This is the page/API execution entry for REQ-002. It only uses an already-connected device and the existing execution modules.
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Union

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from tools.req001.actions import execute_action
from tools.req001.adb_utils import find_adb, list_devices, run_adb
from tools.req001.ai_runner import Observer, run_scenario
from tools.req001.app_fixture import AdbShell, resolve_target_app
from tools.req001.bdd_parser import iter_scenarios, parse_feature_file
from tools.req001.errors import EnvNotReadyError, LlmConfigError, ParseError, Req001Error
from tools.req001.html_report import CaseResult, RunReport, new_run_id, write_report
from tools.req001.keypad import ensure_keypad_ready, scenario_needs_keypad
from tools.req001.llm_client import OpenAICompatibleClient, load_llm_config
from tools.req001.outcomes import apply_s3_fail_safe

# Tester-safe messages. Do not include secrets, paths, or commands.
DEVICE_OFFLINE_MESSAGE = "所选设备当前不在线，请确认设备已连接后重试"
LLM_NOT_CONFIGURED_MESSAGE = "系统未配置执行环境，请联系管理员"
NO_SCRIPTS_MESSAGE = "请选择至少一条可执行脚本"
SCRIPT_PARSE_MESSAGE = "脚本无法解析，请检查是否为合法的 .feature 文件"
PLATFORM_FAILED_MESSAGE = "执行未能完成，请稍后重试或联系管理员"


PathLike = Union[str, Path]


@dataclass
class RunSelectedResult:
    ok: bool
    message: str
    report_dir: Optional[Path] = None
    report_index: Optional[Path] = None
    run_id: str = ""
    device_serial: str = ""
    app_package: str = ""
    cases: List[CaseResult] = field(default_factory=list)


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _force_stop_and_launch(adb: Path, serial: str, package: str) -> None:
    run_adb(adb, ["shell", "am", "force-stop", package], serial=serial, timeout=20)
    time.sleep(1)
    execute_action({"action": "launch_app"}, adb=adb, serial=serial, app_package=package, nodes=[])
    time.sleep(2)


def _confirm_serial_online(serial: str, *, adb: Optional[Path] = None, list_devices_fn=None) -> Path:
    adb_path = adb or find_adb()
    if adb_path is None and list_devices_fn is None:
        raise EnvNotReadyError(DEVICE_OFFLINE_MESSAGE)
    if list_devices_fn is not None:
        devices = list(list_devices_fn())
    else:
        devices = list_devices(adb_path)
    for device in devices:
        if device.serial == serial and getattr(device, "is_online", False) and device.state == "device":
            return adb_path or find_adb() or Path("adb")
    raise EnvNotReadyError(DEVICE_OFFLINE_MESSAGE)


def _load_client(llm_client=None, load_llm_fn=None) -> OpenAICompatibleClient:
    if llm_client is not None:
        return llm_client
    loader = load_llm_fn or load_llm_config
    try:
        cfg = loader()
    except LlmConfigError as exc:
        raise LlmConfigError(LLM_NOT_CONFIGURED_MESSAGE) from exc
    return OpenAICompatibleClient(cfg)


def _parse_features(feature_paths: Sequence[PathLike]):
    if not feature_paths:
        raise ParseError(NO_SCRIPTS_MESSAGE)
    features = []
    for raw in feature_paths:
        path = Path(raw)
        try:
            features.append(parse_feature_file(path))
        except ParseError as exc:
            raise ParseError(SCRIPT_PARSE_MESSAGE) from exc
        except OSError as exc:
            raise ParseError(SCRIPT_PARSE_MESSAGE) from exc
    scenarios = iter_scenarios(features)
    if not scenarios:
        raise ParseError(SCRIPT_PARSE_MESSAGE)
    return scenarios



def _safe_dir_name(value: str) -> str:
    keep = []
    for ch in value:
        keep.append(ch if ch.isalnum() or ch in {"-", "_", "."} else "_")
    return "".join(keep)[:80] or "case"


def _report_screenshots(out_dir: Path, case: CaseResult) -> List[str]:
    shot_root = out_dir / "screenshots"
    if not shot_root.is_dir():
        return []
    case_dir = shot_root / _safe_dir_name(case.case_id or case.name or "case")
    search = case_dir if case_dir.is_dir() else shot_root
    found = sorted(
        path.relative_to(out_dir).as_posix()
        for path in search.rglob("*")
        if path.is_file()
    )
    return found


def run_selected(
    serial: str,
    feature_paths: Sequence[PathLike],
    output_dir: PathLike,
    *,
    max_steps: int = 20,
    llm_client=None,
    adb: Optional[Path] = None,
    list_devices_fn=None,
    load_llm_fn=None,
    resolve_app_fn=None,
    run_scenario_fn=None,
    write_report_fn=None,
    keypad_check_fn=None,
    allow_device_reboot: bool = True,
    observer_factory=None,
) -> RunSelectedResult:
    """Execute the given features on an already-connected `serial` and write the HTML report.

    Returns ok=True when the platform finished and wrote a report (fixture
    assertion failures such as S3 are expected and still ok=True).
    Returns ok=False for orchestration failures (device offline, LLM missing).
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    run_id = new_run_id()
    started = _ts()
    notes: List[str] = []

    try:
        adb_path = _confirm_serial_online(serial, adb=adb, list_devices_fn=list_devices_fn)
        client = _load_client(llm_client=llm_client, load_llm_fn=load_llm_fn)
        scenarios = _parse_features(feature_paths)
        shell = AdbShell(adb_path, serial)
        resolver = resolve_app_fn or resolve_target_app
        app = resolver(shell)
        notes.extend(getattr(app, "notes", []) or [])
    except LlmConfigError:
        return RunSelectedResult(ok=False, message=LLM_NOT_CONFIGURED_MESSAGE, run_id=run_id, device_serial=serial)
    except EnvNotReadyError as exc:
        message = str(exc) if str(exc) == DEVICE_OFFLINE_MESSAGE else DEVICE_OFFLINE_MESSAGE
        return RunSelectedResult(ok=False, message=message, run_id=run_id, device_serial=serial)
    except ParseError:
        return RunSelectedResult(ok=False, message=SCRIPT_PARSE_MESSAGE, run_id=run_id, device_serial=serial)
    except Req001Error:
        return RunSelectedResult(ok=False, message=PLATFORM_FAILED_MESSAGE, run_id=run_id, device_serial=serial)
    except Exception:
        return RunSelectedResult(ok=False, message=PLATFORM_FAILED_MESSAGE, run_id=run_id, device_serial=serial)

    scenario_runner = run_scenario_fn or run_scenario
    cases: List[CaseResult] = []
    emulator_reboot_used = False

    for scenario in scenarios:
        work = out_dir / "work" / scenario.case_id
        work.mkdir(parents=True, exist_ok=True)
        if observer_factory is not None:
            observer = observer_factory(adb=adb_path, serial=serial, work_dir=work)
        else:
            observer = Observer(adb=adb_path, serial=serial, work_dir=work)

        if scenario_needs_keypad(scenario):
            def _dump(obs=observer, case_id=scenario.case_id):
                return obs.snapshot(prefix=f"{case_id}_keypad")

            def _relaunch():
                _force_stop_and_launch(adb_path, serial, app.package)

            def _reboot():
                nonlocal emulator_reboot_used
                if emulator_reboot_used:
                    return
                emulator_reboot_used = True
                # Reboot the already-connected device only. Do not start a missing emulator.
                run_adb(adb_path, ["reboot"], serial=serial, timeout=30)
                time.sleep(8)
                _force_stop_and_launch(adb_path, serial, app.package)

            checker = keypad_check_fn or ensure_keypad_ready
            check = checker(
                _dump,
                relaunch_fn=_relaunch,
                reboot_fn=_reboot if allow_device_reboot else None,
            )
            notes.append(check.message)
            if not check.visible:
                result = CaseResult(
                    case_id=scenario.case_id,
                    name=scenario.name,
                    status="fail",
                    failure_reason=check.message,
                    screenshots=[],
                    steps=[check.message],
                )
                result = apply_s3_fail_safe(result)
                cases.append(result)
                continue

        try:
            result = scenario_runner(
                scenario,
                app_package=app.package,
                client=client,
                observer=observer,
                max_steps=max_steps,
            )
        except LlmConfigError:
            return RunSelectedResult(
                ok=False,
                message=LLM_NOT_CONFIGURED_MESSAGE,
                run_id=run_id,
                device_serial=serial,
                app_package=app.package,
            )
        result = apply_s3_fail_safe(result)
        cases.append(result)

    report = RunReport(
        run_id=run_id,
        device_serial=serial,
        app_package=app.package,
        app_source=getattr(app, "source", "unknown"),
        cases=cases,
        started_at=started,
        finished_at=_ts(),
        notes=notes,
    )
    writer = write_report_fn or write_report
    index = writer(report, out_dir)
    public_cases = []
    for case in cases:
        public_cases.append(
            CaseResult(
                case_id=case.case_id,
                name=case.name,
                status=case.status,
                failure_reason=case.failure_reason,
                screenshots=_report_screenshots(out_dir, case),
                steps=list(case.steps),
            )
        )
    return RunSelectedResult(
        ok=True,
        message="",
        report_dir=out_dir,
        report_index=Path(index),
        run_id=run_id,
        device_serial=serial,
        app_package=app.package,
        cases=public_cases,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Optional CLI for operators. Not the tester acceptance entry."""
    parser = argparse.ArgumentParser(description="REQ-002 adapter: run selected features on a connected device")
    parser.add_argument("--serial", required=True, help="Already-connected adb serial")
    parser.add_argument("--output-dir", required=True, help="Directory to write the HTML report")
    parser.add_argument("--max-steps", type=int, default=20)
    parser.add_argument("features", nargs="+", help="Paths to .feature files")
    args = parser.parse_args(list(argv) if argv is not None else None)
    result = run_selected(args.serial, args.features, args.output_dir, max_steps=args.max_steps)
    # Do not print absolute paths or secrets.
    if result.ok:
        print(f"completed run_id={result.run_id} cases={len(result.cases)}")
        return 0
    print(result.message, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

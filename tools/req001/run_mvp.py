# -*- coding: utf-8 -*-
"""T6: one-command local orchestration for REQ-001 MVP.

Exit code 0 if the platform finished and wrote a report (S3 fixture failure is expected).
Non-zero only when the environment / LLM / orchestration itself failed.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

# Allow `python tools/req001/run_mvp.py` as well as module execution.
_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from tools.req001.stdio import configure_stdio, safe_print

configure_stdio()

from tools.req001.actions import execute_action
from tools.req001.adb_utils import run_adb
from tools.req001.ai_runner import Observer, run_scenario
from tools.req001.app_fixture import AdbShell, resolve_target_app
from tools.req001.bdd_parser import iter_scenarios, load_features
from tools.req001.emulator import ensure_emulator, wait_for_boot
from tools.req001.env_loader import load_local_env
from tools.req001.errors import EnvNotReadyError, LlmConfigError, Req001Error
from tools.req001.html_report import CaseResult, RunReport, new_run_id, write_report
from tools.req001.keypad import ensure_keypad_ready, scenario_needs_keypad
from tools.req001.llm_client import OpenAICompatibleClient, load_llm_config
from tools.req001.outcomes import apply_s3_fail_safe
from tools.req001.paths import artifacts_dir, bdd_dir, repo_root


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _force_stop_and_launch(adb: Path, serial: str, package: str) -> None:
    run_adb(adb, ["shell", "am", "force-stop", package], serial=serial, timeout=20)
    time.sleep(1)
    execute_action({"action": "launch_app"}, adb=adb, serial=serial, app_package=package, nodes=[])
    time.sleep(2)


def _reboot_emulator(adb: Path, serial: str, timeout: int) -> None:
    safe_print("键区仍不可见，正在重启模拟器…")
    run_adb(adb, ["reboot"], serial=serial, timeout=30)
    wait_for_boot(adb, serial, timeout=timeout)


def run_mvp(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="REQ-001 MVP 一键本地试跑")
    parser.add_argument("--avd", default=None, help="指定 AVD 名称；默认复用在线模拟器或 REQ001_API34")
    parser.add_argument("--timeout", type=int, default=240, help="等待模拟器 boot 的秒数")
    parser.add_argument("--max-steps", type=int, default=20, help="每条用例最大 AI 动作次数")
    parser.add_argument("--output-dir", default=None, help="报告输出目录，默认 artifacts/req001/<run_id>")
    parser.add_argument(
        "--no-emulator-reboot",
        action="store_true",
        help="键区空白时只尝试重启应用，不自动重启模拟器",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    root = repo_root()
    load_local_env(root)
    run_id = new_run_id()
    out_dir = Path(args.output_dir) if args.output_dir else artifacts_dir(root) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    started = _ts()
    notes = []
    emulator_reboot_used = False

    try:
        llm_cfg = load_llm_config(load_files=False)  # already loaded
        client = OpenAICompatibleClient(llm_cfg)
        notes.append(f"LLM: {llm_cfg.redacted_summary()}")
    except LlmConfigError as exc:
        safe_print(str(exc), file=sys.stderr)
        return 2

    try:
        ready = ensure_emulator(avd_name=args.avd, timeout=args.timeout)
    except EnvNotReadyError as exc:
        safe_print(str(exc), file=sys.stderr)
        return 2
    notes.extend(ready.notes)
    safe_print(f"模拟器就绪: serial={ready.serial} reused={ready.reused}")

    shell = AdbShell(ready.adb, ready.serial)
    try:
        app = resolve_target_app(shell)
    except Req001Error as exc:
        safe_print(str(exc), file=sys.stderr)
        return 2
    notes.extend(app.notes)
    safe_print(f"被测应用: package={app.package} source={app.source}")

    try:
        features = load_features(bdd_dir(root))
        scenarios = iter_scenarios(features)
    except Req001Error as exc:
        safe_print(str(exc), file=sys.stderr)
        return 2

    cases = []
    for scenario in scenarios:
        work = out_dir / "work" / scenario.case_id
        observer = Observer(adb=ready.adb, serial=ready.serial, work_dir=work)
        safe_print(f"开始执行 {scenario.case_id} {scenario.name}")

        if scenario_needs_keypad(scenario):
            def _dump():
                return observer.snapshot(prefix=f"{scenario.case_id}_keypad")

            def _relaunch():
                safe_print("未发现数字键区，正在重启被测应用…")
                _force_stop_and_launch(ready.adb, ready.serial, app.package)

            def _reboot():
                nonlocal emulator_reboot_used
                if emulator_reboot_used:
                    return
                emulator_reboot_used = True
                _reboot_emulator(ready.adb, ready.serial, timeout=args.timeout)
                _force_stop_and_launch(ready.adb, ready.serial, app.package)

            check = ensure_keypad_ready(
                _dump,
                relaunch_fn=_relaunch,
                reboot_fn=None if args.no_emulator_reboot else _reboot,
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
                safe_print(f"  结果: {result.status} {result.failure_reason}")
                continue

        try:
            result = run_scenario(
                scenario,
                app_package=app.package,
                client=client,
                observer=observer,
                max_steps=args.max_steps,
            )
        except LlmConfigError as exc:
            safe_print(str(exc), file=sys.stderr)
            return 2
        result = apply_s3_fail_safe(result)
        cases.append(result)
        safe_print(f"  结果: {result.status} {result.failure_reason}")

    report = RunReport(
        run_id=run_id,
        device_serial=ready.serial,
        app_package=app.package,
        app_source=app.source,
        cases=cases,
        started_at=started,
        finished_at=_ts(),
        notes=notes,
    )
    index = write_report(report, out_dir)
    safe_print(f"报告已写出: {index}")
    safe_print("用浏览器打开上述 index.html 即可查看。S3 失败是夹具预期，不代表编排失败。")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    return run_mvp(argv)


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""T6: one-command local orchestration for REQ-001 MVP.

Exit code 0 if the platform finished and wrote a report (S3 fixture failure is expected).
Non-zero only when the environment / LLM / orchestration itself failed.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

from tools.req001.ai_runner import Observer, run_scenario
from tools.req001.app_fixture import AdbShell, resolve_target_app
from tools.req001.bdd_parser import iter_scenarios, load_features
from tools.req001.emulator import ensure_emulator
from tools.req001.env_loader import load_local_env
from tools.req001.errors import EnvNotReadyError, LlmConfigError, Req001Error
from tools.req001.html_report import RunReport, new_run_id, write_report
from tools.req001.llm_client import OpenAICompatibleClient, load_llm_config
from tools.req001.paths import artifacts_dir, bdd_dir, repo_root


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def run_mvp(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="REQ-001 MVP 一键本地试跑")
    parser.add_argument("--avd", default=None, help="指定 AVD 名称；默认复用在线模拟器或 REQ001_API34")
    parser.add_argument("--timeout", type=int, default=240, help="等待模拟器 boot 的秒数")
    parser.add_argument("--max-steps", type=int, default=20, help="每条用例最大 AI 动作次数")
    parser.add_argument("--output-dir", default=None, help="报告输出目录，默认 artifacts/req001/<run_id>")
    args = parser.parse_args(list(argv) if argv is not None else None)

    root = repo_root()
    load_local_env(root)
    run_id = new_run_id()
    out_dir = Path(args.output_dir) if args.output_dir else artifacts_dir(root) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    started = _ts()
    notes = []

    try:
        llm_cfg = load_llm_config(load_files=False)  # already loaded
        client = OpenAICompatibleClient(llm_cfg)
        notes.append(f"LLM: {llm_cfg.redacted_summary()}")
    except LlmConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        ready = ensure_emulator(avd_name=args.avd, timeout=args.timeout)
    except EnvNotReadyError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    notes.extend(ready.notes)
    print(f"模拟器就绪: serial={ready.serial} reused={ready.reused}")

    shell = AdbShell(ready.adb, ready.serial)
    try:
        app = resolve_target_app(shell)
    except Req001Error as exc:
        print(str(exc), file=sys.stderr)
        return 2
    notes.extend(app.notes)
    print(f"被测应用: package={app.package} source={app.source}")

    try:
        features = load_features(bdd_dir(root))
        scenarios = iter_scenarios(features)
    except Req001Error as exc:
        print(str(exc), file=sys.stderr)
        return 2

    cases = []
    for scenario in scenarios:
        work = out_dir / "work" / scenario.case_id
        observer = Observer(adb=ready.adb, serial=ready.serial, work_dir=work)
        print(f"开始执行 {scenario.case_id} {scenario.name}")
        result = run_scenario(
            scenario,
            app_package=app.package,
            client=client,
            observer=observer,
            max_steps=args.max_steps,
        )
        cases.append(result)
        print(f"  结果: {result.status} {result.failure_reason}")

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
    print(f"报告已写出: {index}")
    print("用浏览器打开上述 index.html 即可查看。S3 失败是夹具预期，不代表编排失败。")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    return run_mvp(argv)


if __name__ == "__main__":
    repo = Path(__file__).resolve().parents[2]
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    raise SystemExit(main())

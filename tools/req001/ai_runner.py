# -*- coding: utf-8 -*-
"""T4: constrained AI step loop. LLM may only pick whitelist actions; no free exploration."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from tools.req001.actions import ActionResult, execute_action, validate_action
from tools.req001.bdd_parser import Scenario, Step
from tools.req001.errors import ActionError, LlmConfigError
from tools.req001.exec_guards import (
    RepeatClickGuard,
    evaluate_calc_completion,
    hierarchy_fingerprint,
    resolve_click_target,
)
from tools.req001.html_report import CaseResult
from tools.req001.llm_client import OpenAICompatibleClient, parse_json_object
from tools.req001.ui_observe import compact_nodes, dump_hierarchy_xml, parse_ui_hierarchy, take_screenshot

DEFAULT_MAX_STEPS = 20

SYSTEM_PROMPT = """你是 Android UI 测试执行器。根据当前 BDD 步骤、已发生动作和精简 UI 层级，只输出一个 JSON 对象，不要 Markdown，不要解释。
对象必须包含字段 action，且 action 只能是以下之一：
- launch_app
- click（需提供 text、resource_id 或 bounds）
- input（需提供 text）
- wait（可选 seconds）
- assert_text（需提供 text）
- assert_app_foreground
- step_done（当前 BDD 步骤已完成）
- fail（需提供 reason）

规则：
1. 被测应用包名由运行时提供，不要假设或编造其他包名。
2. 优先点击层级里已有的控件 text / content_desc / bounds（数字、+、=、等号、C 等），不要猜测坐标；不要点击显示结果的输入框。
3. 不要规划一整条脚本，一次只返回下一步动作。按钮可能只有 content_desc 而没有 text，click 时应使用层级里的 text、content_desc 或 bounds。
4. 当前步骤目标已达成，或已识别到表达式和计算结果时，返回 step_done。
5. 无法继续时返回 fail 并写明 reason。
6. 禁止白名单之外的动作，禁止自主探索无关界面。若上次点击后屏幕没有变化，不要再次点击同一坐标。
"""


@dataclass
class Observer:
    adb: Path
    serial: str
    work_dir: Path
    shot_index: int = 0

    def snapshot(self, prefix: str) -> Tuple[List[Any], Optional[Path], List[dict]]:
        self.work_dir.mkdir(parents=True, exist_ok=True)
        xml = dump_hierarchy_xml(self.adb, self.serial, self.work_dir)
        nodes = parse_ui_hierarchy(xml)
        compact = compact_nodes(nodes)
        self.shot_index += 1
        dest = self.work_dir / "screenshots" / f"{prefix}_{self.shot_index:03d}.png"
        path = take_screenshot(self.adb, self.serial, dest)
        return nodes, path, compact


# Injectable hooks for unit tests (no device / no model).
DumpFn = Callable[[], Tuple[list, Optional[Path], List[dict]]]
ExecFn = Callable[[Dict[str, Any], list], ActionResult]
DecideFn = Callable[[List[Dict[str, str]]], str]


def _messages_for(step: Step, history: Sequence[str], compact: List[dict], app_package: str, case_name: str) -> List[Dict[str, str]]:
    user = {
        "case": case_name,
        "app_package": app_package,
        "current_step": {"keyword": step.keyword, "text": step.text},
        "recent_actions": list(history[-8:]),
        "ui": compact,
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


def run_scenario(
    scenario: Scenario,
    *,
    app_package: str,
    client: OpenAICompatibleClient,
    observer: Optional[Observer] = None,
    dump_fn: Optional[DumpFn] = None,
    exec_fn: Optional[ExecFn] = None,
    max_steps: int = DEFAULT_MAX_STEPS,
) -> CaseResult:
    screenshots: List[str] = []
    traces: List[str] = []
    history: List[str] = []
    total_actions = 0

    def _dump():
        if dump_fn:
            return dump_fn()
        if observer is None:
            raise ActionError("未配置界面采集器")
        return observer.snapshot(prefix=scenario.case_id)

    def _exec(action: Dict[str, Any], nodes: list) -> ActionResult:
        if exec_fn:
            return exec_fn(action, nodes)
        if observer is None:
            raise ActionError("未配置动作执行器")
        return execute_action(
            action,
            adb=observer.adb,
            serial=observer.serial,
            app_package=app_package,
            nodes=nodes,
        )

    def _record_shot(path: Optional[Path]) -> None:
        if path and Path(path).is_file():
            screenshots.append(str(path))

    click_guard = RepeatClickGuard()

    def _fail(reason: str) -> CaseResult:
        traces.append(reason)
        return CaseResult(
            case_id=scenario.case_id,
            name=scenario.name,
            status="fail",
            failure_reason=reason,
            screenshots=screenshots,
            steps=traces,
        )

    def _pass() -> CaseResult:
        return CaseResult(
            case_id=scenario.case_id,
            name=scenario.name,
            status="pass",
            failure_reason="",
            screenshots=screenshots,
            steps=traces,
        )

    try:
        for step in scenario.steps:
            step_actions = 0
            while True:
                if total_actions >= max_steps:
                    return _fail(f"超过每条用例最大步数 {max_steps}，已停止")
                nodes, shot, compact = _dump()
                _record_shot(shot)
                fingerprint = hierarchy_fingerprint(nodes)
                click_guard.observe(fingerprint)

                completion = evaluate_calc_completion(scenario, step, nodes, history)
                if completion.kind == "when_done":
                    summary = f"{step.keyword} {step.text} -> step_done: {completion.message}"
                    traces.append(summary)
                    history.append(summary)
                    total_actions += 1
                    break
                if completion.kind == "pass_case":
                    summary = f"{step.keyword} {step.text} -> step_done: {completion.message}"
                    traces.append(summary)
                    history.append(summary)
                    total_actions += 1
                    return _pass()
                if completion.kind == "fail_case":
                    summary = f"{step.keyword} {step.text} -> assert_text: {completion.message}"
                    traces.append(summary)
                    history.append(summary)
                    total_actions += 1
                    return _fail(completion.message)

                messages = _messages_for(step, history, compact, app_package, scenario.name)
                raw = client.complete(messages)
                try:
                    payload = parse_json_object(raw)
                    validate_action(payload)
                except (ValueError, ActionError) as exc:
                    return _fail(f"非法或不可解析动作: {exc}")

                target = None
                if str(payload.get("action") or "") == "click":
                    target = resolve_click_target(payload, nodes)
                    if target is not None and click_guard.blocks((target.x, target.y)):
                        result = ActionResult(
                            ok=False,
                            message=click_guard.reject_message((target.x, target.y)),
                            click_xy=(target.x, target.y),
                        )
                        total_actions += 1
                        step_actions += 1
                        summary = f"{step.keyword} {step.text} -> click: {result.message}"
                        traces.append(summary)
                        history.append(summary)
                        continue

                try:
                    result = _exec(payload, nodes)
                except ActionError as exc:
                    result = ActionResult(ok=False, message=str(exc))
                total_actions += 1
                step_actions += 1
                summary = f"{step.keyword} {step.text} -> {payload.get('action')}: {result.message}"
                traces.append(summary)
                history.append(summary)
                click_xy = result.click_xy
                if click_xy is None and target is not None:
                    click_xy = (target.x, target.y)
                if str(payload.get("action") or "") == "click" and result.ok and click_xy:
                    click_guard.record_click(click_xy)
                if result.step_done:
                    break
                if result.assertion_failed or result.abort:
                    return _fail(result.message or "步骤失败")
                # Recoverable action failures (e.g. a missed click) stay in the step loop.
        return _pass()
    except LlmConfigError:
        raise
    except Exception as exc:
        traces.append(f"执行异常: {type(exc).__name__}")
        return CaseResult(
            case_id=scenario.case_id,
            name=scenario.name,
            status="fail",
            failure_reason=f"执行异常: {type(exc).__name__}: {exc}",
            screenshots=screenshots,
            steps=traces,
        )

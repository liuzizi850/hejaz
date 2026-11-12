# -*- coding: utf-8 -*-
import json
from pathlib import Path

import pytest

from tools.req001.actions import ActionResult, validate_action, WHITELIST
from tools.req001.ai_runner import run_scenario
from tools.req001.bdd_parser import parse_gherkin
from tools.req001.errors import ActionError, LlmConfigError
from tools.req001.llm_client import OpenAICompatibleClient, LlmConfig, parse_json_object, load_llm_config
from tools.req001.ui_observe import parse_ui_hierarchy, compact_nodes


FEATURE = """
功能: demo
  场景: REQ-001-S1 打开被测应用
    假如 被测应用已安装
    当 启动被测应用
    那么 被测应用进入前台
"""

HIERARCHY = """<?xml version='1.0' encoding='UTF-8'?>
<hierarchy>
  <node text="" package="demo.app" clickable="false" bounds="[0,0][100,100]">
    <node text="1" clickable="true" resource-id="demo.app:id/digit_1" bounds="[0,80][20,100]"/>
    <node text="+" clickable="true" bounds="[20,80][40,100]"/>
    <node text="2" clickable="true" bounds="[80,0][100,20]"/>
  </node>
</hierarchy>
"""


def _scenario():
    return parse_gherkin(FEATURE).scenarios[0]


def _client(script):
    def completer(messages, temperature=0.0):
        return script.pop(0) if script else json.dumps({"action": "fail", "reason": "script exhausted"})

    return OpenAICompatibleClient(LlmConfig(api_key="dummy", base_url="http://example.invalid/v1", model="dummy"), completer=completer)


def test_parse_hierarchy_keeps_clickable_and_text():
    nodes = parse_ui_hierarchy(HIERARCHY)
    compact = compact_nodes(nodes)
    texts = {n["text"] for n in compact if "text" in n}
    assert {"1", "+", "2"} <= texts


def test_mock_llm_runs_case_to_completion(tmp_path):
    shot = tmp_path / "s.png"
    shot.write_bytes(b"png")
    script = [
        json.dumps({"action": "step_done"}),
        json.dumps({"action": "launch_app"}),
        json.dumps({"action": "step_done"}),
        json.dumps({"action": "assert_app_foreground"}),
        json.dumps({"action": "step_done"}),
    ]
    executed = []

    def dump():
        from tools.req001.ui_observe import parse_ui_hierarchy

        return parse_ui_hierarchy(HIERARCHY), shot, []

    def exec_fn(action, nodes):
        executed.append(action["action"])
        if action["action"] == "step_done":
            return ActionResult(ok=True, step_done=True, message="done")
        return ActionResult(ok=True, message="ok")

    result = run_scenario(
        _scenario(),
        app_package="demo.app",
        client=_client(script),
        dump_fn=dump,
        exec_fn=exec_fn,
    )
    assert result.status == "pass"
    assert "launch_app" in executed
    assert result.screenshots
    assert result.failure_reason == ""


def test_assertion_failure_stops_case():
    shot = Path("unused")
    script = [
        json.dumps({"action": "step_done"}),
        json.dumps({"action": "step_done"}),
        json.dumps({"action": "assert_text", "text": "3"}),
    ]

    def dump():
        return [], None, []

    def exec_fn(action, nodes):
        if action["action"] == "step_done":
            return ActionResult(ok=True, step_done=True)
        if action["action"] == "assert_text":
            return ActionResult(ok=False, assertion_failed=True, abort=True, message="断言失败：期望看到「3」，实际界面未出现该文本")
        return ActionResult(ok=True)

    result = run_scenario(_scenario(), app_package="demo.app", client=_client(script), dump_fn=dump, exec_fn=exec_fn)
    assert result.status == "fail"
    assert "期望看到「3」" in result.failure_reason


def test_illegal_action_is_rejected():
    with pytest.raises(ActionError):
        validate_action({"action": "explore_freely"})
    assert "explore_freely" not in WHITELIST

    script = [json.dumps({"action": "shell", "cmd": "rm -rf /"})]

    def dump():
        return [], None, []

    result = run_scenario(_scenario(), app_package="demo.app", client=_client(script), dump_fn=dump, exec_fn=lambda a, n: ActionResult(ok=True))
    assert result.status == "fail"
    assert "非法" in result.failure_reason


def test_max_steps_recorded_as_failure():
    script = [json.dumps({"action": "wait", "seconds": 0})] * 10

    def dump():
        return [], None, []

    def exec_fn(action, nodes):
        return ActionResult(ok=True, message="wait")

    result = run_scenario(
        _scenario(),
        app_package="demo.app",
        client=_client(script),
        dump_fn=dump,
        exec_fn=exec_fn,
        max_steps=3,
    )
    assert result.status == "fail"
    assert "最大步数" in result.failure_reason


def test_missing_llm_config_is_clear(monkeypatch):
    for key in ("OPENAI_API_KEY", "REQ001_OPENAI_API_KEY", "OPENAI_MODEL", "JUDGE_MODEL", "REQ001_OPENAI_MODEL", "REQ001_LLM_MODEL"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(LlmConfigError) as exc:
        load_llm_config(load_files=False)
    msg = str(exc.value)
    assert "OPENAI_API_KEY" in msg
    assert "人工点选" in msg


def test_parse_json_object_accepts_fences():
    data = parse_json_object("```json\n{\"action\": \"step_done\"}\n```")
    assert data["action"] == "step_done"

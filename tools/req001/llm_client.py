# -*- coding: utf-8 -*-
"""OpenAI-compatible chat client configured only from local env / config.

No vendor is hard-coded. API keys are never written to logs, reports, or exceptions.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from tools.req001.env_loader import load_local_env
from tools.req001.errors import LlmConfigError

# Names only — never log the corresponding values.
_KEY_VARS = ("REQ001_OPENAI_API_KEY", "OPENAI_API_KEY")
_BASE_VARS = ("REQ001_OPENAI_BASE_URL", "OPENAI_BASE_URL")
_MODEL_VARS = ("REQ001_OPENAI_MODEL", "OPENAI_MODEL", "REQ001_LLM_MODEL", "JUDGE_MODEL")

SETUP_HINT = """未检测到可用的 LLM 配置，无法自动执行用例（不会退回人工点选）。

请在本机环境变量或仓库根目录的 .env（git 已忽略，切勿提交）中配置 OpenAI 兼容接口：
  OPENAI_API_KEY    必填
  OPENAI_BASE_URL   可选，兼容网关或本地服务的 base URL
  OPENAI_MODEL      可选；若未设置则尝试 JUDGE_MODEL / REQ001_OPENAI_MODEL

在 worktree 中运行时，脚本也会尝试读取主工作区中的 .env，但不会复制或打印它。
配置完成后重新运行同一条命令。
"""


def _first_env(names) -> str:
    for name in names:
        value = os.environ.get(name, "")
        if value and value.strip():
            return value.strip()
    return ""


@dataclass
class LlmConfig:
    api_key: str
    base_url: Optional[str]
    model: str

    def redacted_summary(self) -> str:
        url = self.base_url or "（默认端点）"
        return f"model={self.model}; base_url={url}; api_key=***（已配置，长度不在日志中展开）"


def load_llm_config(load_files: bool = True) -> LlmConfig:
    if load_files:
        load_local_env()
    api_key = _first_env(_KEY_VARS)
    base_url = _first_env(_BASE_VARS) or None
    model = _first_env(_MODEL_VARS)
    missing = []
    if not api_key:
        missing.append("OPENAI_API_KEY")
    if not model:
        missing.append("OPENAI_MODEL 或 JUDGE_MODEL")
    if missing:
        raise LlmConfigError("缺少 " + "、".join(missing) + "。\n" + SETUP_HINT)
    return LlmConfig(api_key=api_key, base_url=base_url, model=model)


class OpenAICompatibleClient:
    """Thin chat wrapper. The api_key is kept on the instance and never stringified."""

    def __init__(self, config: LlmConfig, completer: Optional[Callable[..., str]] = None):
        self._config = config
        self._completer = completer

    @classmethod
    def from_env(cls, load_files: bool = True) -> "OpenAICompatibleClient":
        return cls(load_llm_config(load_files=load_files))

    def complete(self, messages: List[Dict[str, str]], temperature: float = 0.0) -> str:
        if self._completer is not None:
            return self._completer(messages=messages, temperature=temperature)
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise LlmConfigError(
                "当前 Python 环境未安装 openai 包，无法调用 OpenAI 兼容接口。请在项目虚拟环境中安装后重试。"
            ) from exc
        kwargs: Dict[str, Any] = {"api_key": self._config.api_key}
        if self._config.base_url:
            kwargs["base_url"] = self._config.base_url
        client = OpenAI(**kwargs)
        try:
            response = client.chat.completions.create(
                model=self._config.model,
                messages=messages,
                temperature=temperature,
            )
        except Exception as exc:
            # Make sure unexpected exception text does not echo a key if it was interpolated elsewhere.
            raise LlmConfigError(f"调用 LLM 失败: {type(exc).__name__}") from exc
        try:
            return (response.choices[0].message.content or "").strip()
        except Exception as exc:
            raise LlmConfigError("LLM 返回无法解析的响应") from exc


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def parse_json_object(text: str) -> Dict[str, Any]:
    if not text or not text.strip():
        raise ValueError("LLM 返回空内容")
    blob = text.strip()
    fenced = _FENCE_RE.search(blob)
    if fenced:
        blob = fenced.group(1).strip()
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        start = blob.find("{")
        end = blob.rfind("}")
        if start >= 0 and end > start:
            data = json.loads(blob[start : end + 1])
        else:
            raise
    if not isinstance(data, dict):
        raise ValueError("LLM 返回的 JSON 不是对象")
    return data

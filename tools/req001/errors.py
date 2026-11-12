# -*- coding: utf-8 -*-
"""REQ-001 typed errors with operator-facing messages."""


class Req001Error(Exception):
    """Base error for the isolated MVP path."""


class EnvNotReadyError(Req001Error):
    """SDK / emulator / AVD / device is missing or not boot-complete."""


class LlmConfigError(Req001Error):
    """OpenAI-compatible LLM configuration is missing or invalid."""


class AppFixtureError(Req001Error):
    """Target app discovery or fallback APK install failed."""


class ActionError(Req001Error):
    """A whitelist UI action could not be executed or was illegal."""


class ParseError(Req001Error):
    """BDD fixture could not be parsed."""

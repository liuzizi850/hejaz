# -*- coding: utf-8 -*-

def execution_kind(test_case):
    chain = getattr(test_case, "event_chain", None) or {}
    if isinstance(chain, dict) and chain.get("steps"):
        return "event_chain"
    return "ui_flow"

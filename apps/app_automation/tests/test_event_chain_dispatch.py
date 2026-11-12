from types import SimpleNamespace
from apps.app_automation.recording.dispatch import execution_kind


def test_empty_chain_stays_on_ui_flow():
    case = SimpleNamespace(event_chain={}, ui_flow={"steps": [{"type": "click"}]})
    assert execution_kind(case) == "ui_flow"


def test_steps_select_event_chain():
    case = SimpleNamespace(event_chain={"steps": [{"type": "click"}]}, ui_flow={"steps": [{"type": "click"}]})
    assert execution_kind(case) == "event_chain"

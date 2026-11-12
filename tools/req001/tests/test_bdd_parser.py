# -*- coding: utf-8 -*-
from pathlib import Path

import pytest

from tools.req001.bdd_parser import (
    fixture_hardcoded_packages,
    load_features,
    parse_gherkin,
    iter_scenarios,
)
from tools.req001.errors import ParseError
from tools.req001.paths import bdd_dir, repo_root


def test_parse_three_repo_fixtures():
    features = load_features(bdd_dir())
    scenarios = iter_scenarios(features)
    ids = [s.case_id for s in scenarios]
    assert ids == ["REQ-001-S1", "REQ-001-S2", "REQ-001-S3"]
    names = {s.case_id: s.name for s in scenarios}
    assert "打开被测应用" in names["REQ-001-S1"]
    assert "1+1" in names["REQ-001-S2"] and "2" in names["REQ-001-S2"]
    assert "3" in names["REQ-001-S3"]
    # Each scenario has Given/When/Then style steps consumable by T4
    for sc in scenarios:
        kinds = [st.keyword for st in sc.steps]
        assert kinds[0] in {"given", "when"}
        assert "then" in kinds
        assert all(st.text.strip() for st in sc.steps)
        joined = " ".join(st.text for st in sc.steps)
        assert "被测应用" in joined


def test_fixtures_do_not_hardcode_package_names():
    features = load_features(bdd_dir())
    assert fixture_hardcoded_packages(features) == []


def test_english_keywords_and_and_steps():
    text = """
Feature: Open the app under test
  Scenario: REQ-001-S1 open
    Given the app under test is installed
    When the app under test is launched
    And the splash is dismissed if shown
    Then the app under test is in the foreground
"""
    feature = parse_gherkin(text)
    steps = feature.scenarios[0].steps
    assert [s.keyword for s in steps] == ["given", "when", "and", "then"]
    assert steps[2].text.startswith("the splash")


def test_parse_error_on_empty_feature():
    with pytest.raises(ParseError):
        parse_gherkin("Feature: only title\n")


def test_and_cannot_be_first_step():
    text = """
功能: x
  场景: y
    而且 不能作为第一步
"""
    with pytest.raises(ParseError):
        parse_gherkin(text)

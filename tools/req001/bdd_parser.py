# -*- coding: utf-8 -*-
"""Minimal read-only Gherkin parser for REQ-001 fixtures (Feature/Scenario/Given/When/Then/And)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from tools.req001.errors import ParseError

# English keywords plus common Chinese Gherkin aliases. Fixtures are written in Chinese.
_KEYWORD_MAP = {
    "feature": "feature",
    "功能": "feature",
    "特性": "feature",
    "scenario": "scenario",
    "场景": "scenario",
    "情景": "scenario",
    "given": "given",
    "假如": "given",
    "假设": "given",
    "假定": "given",
    "given that": "given",
    "when": "when",
    "当": "when",
    "then": "then",
    "那么": "then",
    "则": "then",
    "and": "and",
    "而且": "and",
    "并且": "and",
    "同时": "and",
    "but": "but",
    "但是": "but",
}

_KEYWORD_RE = re.compile(
    r"^(?P<keyword>"
    + "|".join(sorted((re.escape(k) for k in _KEYWORD_MAP), key=len, reverse=True))
    + r")(?:\s*[:：]\s*|\s+)(?P<rest>.*)$",
    re.IGNORECASE,
)

_SCENARIO_ID_RE = re.compile(r"(REQ-001-S\d+)", re.IGNORECASE)

# Placeholders allowed in fixtures; real package names must not be hard-coded.
ALLOWED_APP_PLACEHOLDERS = ("被测应用", "{app_package}", "<app_package>", "APP_PACKAGE")


@dataclass
class Step:
    keyword: str  # given/when/then/and/but
    text: str
    raw_keyword: str
    line: int


@dataclass
class Scenario:
    name: str
    case_id: str
    steps: List[Step] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    source_file: Optional[str] = None
    line: int = 0


@dataclass
class Feature:
    name: str
    scenarios: List[Scenario] = field(default_factory=list)
    source_file: Optional[str] = None
    language: Optional[str] = None


def _strip_comment(line: str) -> str:
    in_single = False
    in_double = False
    for i, ch in enumerate(line):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            return line[:i].rstrip()
    return line.rstrip()


def _parse_language(line: str) -> Optional[str]:
    match = re.match(r"^#\s*language\s*:\s*(\S+)", line.strip(), re.IGNORECASE)
    return match.group(1) if match else None


def _split_tags(line: str) -> List[str]:
    return [tok[1:] for tok in line.split() if tok.startswith("@")]


def _derive_case_id(name: str, source: Optional[Path], fallback_index: int) -> str:
    match = _SCENARIO_ID_RE.search(name)
    if match:
        return match.group(1).upper()
    if source:
        match = _SCENARIO_ID_RE.search(source.name)
        if match:
            return match.group(1).upper()
    return f"SCENARIO-{fallback_index}"


def parse_gherkin(text: str, source: Optional[Path] = None) -> Feature:
    """Parse a single feature document. Raises ParseError on empty/invalid input."""
    if text is None:
        raise ParseError("夹具内容为空")
    lines = text.splitlines()
    feature = Feature(name="", source_file=str(source) if source else None)
    pending_tags: List[str] = []
    current: Optional[Scenario] = None
    last_step_kind: Optional[str] = None
    scenario_index = 0

    for lineno, raw in enumerate(lines, start=1):
        if raw.strip().startswith("#"):
            lang = _parse_language(raw)
            if lang:
                feature.language = lang
            continue
        line = _strip_comment(raw).strip()
        if not line:
            continue
        if line.startswith("@"):
            pending_tags.extend(_split_tags(line))
            continue

        match = _KEYWORD_RE.match(line)
        if not match:
            # Gherkin allows free-text descriptions under Feature / before steps.
            if current is None or not current.steps:
                continue
            raise ParseError(f"{source or '<memory>'}:{lineno}: 无法识别的语句: {line}")

        raw_kw = match.group("keyword")
        kind = _KEYWORD_MAP[raw_kw.lower() if raw_kw.lower() in _KEYWORD_MAP else raw_kw]
        rest = match.group("rest").strip()

        if kind == "feature":
            if feature.name:
                raise ParseError(f"{source or '<memory>'}:{lineno}: 同一文件中出现多个 Feature")
            feature.name = rest
            pending_tags = []
            current = None
            last_step_kind = None
            continue

        if kind == "scenario":
            if not feature.name:
                raise ParseError(f"{source or '<memory>'}:{lineno}: Scenario 出现在 Feature 之前")
            scenario_index += 1
            current = Scenario(
                name=rest,
                case_id=_derive_case_id(rest, source, scenario_index),
                tags=list(pending_tags),
                source_file=str(source) if source else None,
                line=lineno,
            )
            feature.scenarios.append(current)
            pending_tags = []
            last_step_kind = None
            continue

        if current is None:
            raise ParseError(f"{source or '<memory>'}:{lineno}: 步骤出现在 Scenario 之外")
        if kind in {"and", "but"} and last_step_kind is None:
            raise ParseError(f"{source or '<memory>'}:{lineno}: And/But 不能作为第一条步骤")
        current.steps.append(Step(keyword=kind, text=rest, raw_keyword=raw_kw, line=lineno))
        if kind not in {"and", "but"}:
            last_step_kind = kind

    if not feature.name:
        raise ParseError(f"{source or '<memory>'}: 缺少 Feature 标题")
    if not feature.scenarios:
        raise ParseError(f"{source or '<memory>'}: Feature「{feature.name}」中没有任何 Scenario")
    for sc in feature.scenarios:
        if not sc.steps:
            raise ParseError(f"{source or '<memory>'}: Scenario「{sc.name}」没有任何步骤")
    return feature


def parse_feature_file(path: Path) -> Feature:
    path = Path(path)
    if not path.is_file():
        raise ParseError(f"找不到夹具文件: {path}")
    text = path.read_text(encoding="utf-8")
    return parse_gherkin(text, source=path)


def load_features(directory: Path) -> List[Feature]:
    directory = Path(directory)
    if not directory.is_dir():
        raise ParseError(f"找不到夹具目录: {directory}")
    files = sorted(directory.glob("*.feature"))
    if not files:
        raise ParseError(f"夹具目录为空: {directory}")
    return [parse_feature_file(path) for path in files]


def iter_scenarios(features: Iterable[Feature]) -> List[Scenario]:
    scenarios: List[Scenario] = []
    for feature in features:
        scenarios.extend(feature.scenarios)
    return scenarios


_PACKAGE_RE = re.compile(r"\bcom\.[a-zA-Z0-9_.]+\b")


def fixture_hardcoded_packages(features: Sequence[Feature]) -> List[str]:
    """Return any dotted package-like tokens found in fixture text (should be empty)."""
    found: List[str] = []
    for feature in features:
        blobs = [feature.name]
        for sc in feature.scenarios:
            blobs.append(sc.name)
            blobs.extend(step.text for step in sc.steps)
        for blob in blobs:
            for match in _PACKAGE_RE.findall(blob):
                if match not in found:
                    found.append(match)
    return found

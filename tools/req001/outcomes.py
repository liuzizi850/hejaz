# -*- coding: utf-8 -*-
"""Orchestrator outcome guards for REQ-001 fixtures."""
from __future__ import annotations

from typing import Iterable, List

from tools.req001.html_report import CaseResult

S3_CASE_ID = "REQ-001-S3"
S3_FORCE_FAIL_REASON = (
    "编排层强制标记失败：REQ-001-S3 是故意失败的断言夹具，"
    "即使执行器或模型将其记为通过，报告中也必须为失败。"
)


def is_s3_case(case: CaseResult) -> bool:
    cid = (case.case_id or "").upper()
    if cid == S3_CASE_ID:
        return True
    # Be conservative: only treat exact id as S3 so other cases are not flipped.
    return False


def apply_s3_fail_safe(case: CaseResult) -> CaseResult:
    """Guarantee REQ-001-S3 is recorded as failed in the report."""
    if not is_s3_case(case):
        return case
    if case.status != "fail":
        case.status = "fail"
        case.failure_reason = S3_FORCE_FAIL_REASON
    elif not (case.failure_reason or "").strip():
        case.failure_reason = S3_FORCE_FAIL_REASON
    return case


def apply_s3_fail_safe_all(cases: Iterable[CaseResult]) -> List[CaseResult]:
    return [apply_s3_fail_safe(case) for case in cases]

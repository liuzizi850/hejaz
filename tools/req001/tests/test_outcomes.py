# -*- coding: utf-8 -*-
from pathlib import Path

from tools.req001.html_report import CaseResult, RunReport, write_report
from tools.req001.outcomes import S3_FORCE_FAIL_REASON, apply_s3_fail_safe, apply_s3_fail_safe_all


def test_s3_passed_by_model_is_forced_failed():
    case = CaseResult(case_id="REQ-001-S3", name="计算 1+1 断言等于 3", status="pass", failure_reason="")
    out = apply_s3_fail_safe(case)
    assert out.status == "fail"
    assert "强制" in out.failure_reason or "S3" in out.failure_reason
    assert out.failure_reason == S3_FORCE_FAIL_REASON


def test_s3_already_failed_keeps_original_reason():
    reason = "断言失败：期望看到「3」，实际界面未出现该文本"
    case = CaseResult(case_id="REQ-001-S3", name="计算 1+1 断言等于 3", status="fail", failure_reason=reason)
    out = apply_s3_fail_safe(case)
    assert out.status == "fail"
    assert out.failure_reason == reason


def test_s1_and_s2_are_not_flipped():
    s1 = CaseResult(case_id="REQ-001-S1", name="打开被测应用", status="pass")
    s2 = CaseResult(case_id="REQ-001-S2", name="计算 1+1 等于 2", status="pass")
    assert apply_s3_fail_safe(s1).status == "pass"
    assert apply_s3_fail_safe(s2).status == "pass"


def test_report_html_shows_forced_s3_failure(tmp_path: Path):
    cases = apply_s3_fail_safe_all(
        [
            CaseResult(case_id="REQ-001-S2", name="计算 1+1 等于 2", status="pass"),
            CaseResult(case_id="REQ-001-S3", name="计算 1+1 断言等于 3", status="pass"),
        ]
    )
    report = RunReport(
        run_id="force-s3",
        device_serial="emulator-5554",
        app_package="demo.app",
        app_source="fallback_apk",
        cases=cases,
    )
    index = write_report(report, tmp_path / "report")
    html = index.read_text(encoding="utf-8")
    assert "REQ-001-S3" in html
    assert "失败" in html
    assert "通过" in html  # S2
    assert "class=\"case fail\"" in html or "case fail" in html
    assert "强制" in html or "故意失败" in html or "必须为失败" in html

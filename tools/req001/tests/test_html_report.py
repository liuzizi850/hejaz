# -*- coding: utf-8 -*-
import base64
from pathlib import Path

from tools.req001.html_report import CaseResult, RunReport, write_report

# 1x1 PNG
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def test_html_report_contains_required_fields(tmp_path: Path):
    shot_pass = tmp_path / "s1.png"
    shot_fail = tmp_path / "s3.png"
    shot_pass.write_bytes(_PNG)
    shot_fail.write_bytes(_PNG)

    report = RunReport(
        run_id="20260101_010101",
        device_serial="emulator-5554",
        app_package="demo.package.from.metadata",
        app_source="fallback_apk",
        started_at="2026-01-01 01:01:01",
        finished_at="2026-01-01 01:02:00",
        notes=["示例报告，用于无设备验证"],
        cases=[
            CaseResult(
                case_id="REQ-001-S1",
                name="打开被测应用",
                status="pass",
                screenshots=[str(shot_pass)],
            ),
            CaseResult(
                case_id="REQ-001-S3",
                name="计算 1+1 断言等于 3",
                status="fail",
                failure_reason="断言失败：期望看到「3」，实际界面未出现该文本（可见结果为 2）",
                screenshots=[str(shot_fail)],
            ),
        ],
    )
    out = tmp_path / "artifacts" / "req001" / report.run_id
    index = write_report(report, out)
    assert index.is_file()
    html = index.read_text(encoding="utf-8")
    assert "REQ-001-S1" in html and "打开被测应用" in html
    assert "通过" in html and "失败" in html
    assert "断言失败：期望看到「3」" in html
    assert "emulator-5554" in html
    assert "demo.package.from.metadata" in html
    assert "仓库备选 APK" in html
    assert "screenshots/" in html
    # Images were copied next to the html
    copied = list((out / "screenshots").rglob("*.png"))
    assert len(copied) == 2
    # Browser-openable relative src, not Allure
    assert "allure-results" not in html.lower() and "allure-report" not in html.lower()
    assert "不依赖 Allure" in html or "不依赖 allure" in html.lower()

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment

from apps.code_monitor.extract import EXCEL_HEADERS, ApiRow
from apps.code_monitor.review import OMISSION_LABEL, VERDICT_LABEL, VULN_LABEL, summary_counts
from apps.code_monitor.sample_data import render_request_sample
from apps.code_monitor.test_points import render_test_points


def _excel_text(value: str) -> str:
    if value[:1] in "=+-@":
        return "'" + value
    return value


def write_api_workbook(rows: list[ApiRow]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "API"
    sheet.append(EXCEL_HEADERS)
    for row in rows:
        sheet.append([
            _excel_text(row.name),
            row.method,
            _excel_text(row.url),
            _excel_text(row.request_params),
            _excel_text(render_request_sample(row.request_params)),
            _excel_text(render_test_points(row.request_params)),
            _excel_text(row.response_params),
            _excel_text(row.source_file),
        ])
    for column, width in {"D": 40, "E": 48, "F": 56, "G": 36}.items():
        sheet.column_dimensions[column].width = width
    for cells in sheet.iter_rows(min_row=2, min_col=4, max_col=7):
        for cell in cells:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


PRIORITY_HEADERS = ["编号", "需求点", "代码情况", "测试建议", "建议优先级", "位置", "说明"]
OMISSION_HEADERS = ["编号", "需求点", "缺口类型", "缺口", "前置条件", "步骤要点", "预期", "位置"]
VULN_HEADERS = ["编号", "需求点", "风险类型", "风险", "怎么测", "预期", "位置"]


def write_review_workbook(report) -> bytes:
    workbook = Workbook()
    summary = workbook.active
    summary.title = "汇总"
    counts = summary_counts(report.findings)
    rows = [
        ("需求原文", report.requirement),
        ("检查点总数", counts["total"]),
        ("建议优先测试", counts["high"]),
        ("可少测的主流程", counts["light"]),
        ("待确认未实现", counts["missing"]),
        ("安全测试点", counts["vulnerabilities"]),
        ("无法检查", counts["uncheckable"]),
    ]
    summary.append(["项目", "内容"])
    for label, value in rows:
        summary.append([label, value if isinstance(value, int) else _excel_text(str(value))])
    for cell in summary["B"]:
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    summary.column_dimensions["A"].width = 20
    summary.column_dimensions["B"].width = 80

    priority = workbook.create_sheet("测试优先级")
    priority.append(PRIORITY_HEADERS)
    supplement = workbook.create_sheet("补测用例")
    supplement.append(OMISSION_HEADERS)
    security = workbook.create_sheet("安全测试点")
    security.append(VULN_HEADERS)
    for finding in report.findings:
        priority.append([
            finding.number,
            _excel_text(finding.text),
            VERDICT_LABEL.get(finding.verdict, finding.verdict),
            _excel_text(finding.advice),
            finding.priority,
            _excel_text(finding.evidence_path),
            _excel_text(finding.evidence_note),
        ])
        for item in finding.omissions:
            supplement.append([
                finding.number,
                _excel_text(finding.text),
                OMISSION_LABEL.get(item.kind, item.kind),
                _excel_text(item.gap),
                _excel_text(item.precondition),
                _excel_text(item.steps),
                _excel_text(item.expected),
                _excel_text(item.path),
            ])
        for item in finding.vulnerabilities:
            security.append([
                finding.number,
                _excel_text(finding.text),
                VULN_LABEL.get(item.kind, item.kind),
                _excel_text(item.risk),
                _excel_text(item.how_to_test),
                _excel_text(item.expected),
                _excel_text(item.path),
            ])
    for sheet in (priority, supplement, security):
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()

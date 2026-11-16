from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment

from apps.code_monitor.extract import EXCEL_HEADERS, ApiRow
from apps.code_monitor.sample_data import render_request_sample
from apps.code_monitor.test_points import render_test_points


def _excel_text(value: str) -> str:
    if value.startswith(("=", "+", "-", "@")):
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


FILTER_HEADERS = ["需求", "操作", "遗漏点"]
_NOT_SEEN = ("未出现", "未涉及", "未检索到", "没有找到", "无法判断", "对不上", "无法从给定片段判断")


def _operation(steps: str, gap: str) -> str:
    text = (steps or "").strip()
    if not text or text == gap:
        return "按该需求操作"
    return text


def write_review_workbook(report) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "测试过滤"
    sheet.append(FILTER_HEADERS)
    for finding in report.findings:
        wrote = False
        for item in finding.omissions:
            sheet.append([
                _excel_text(finding.text),
                _excel_text(_operation(item.steps, item.gap)),
                _excel_text(item.gap),
            ])
            wrote = True
        for item in finding.vulnerabilities:
            sheet.append([
                _excel_text(finding.text),
                "做该需求相关操作时",
                _excel_text(item.risk),
            ])
            wrote = True
        if not wrote and finding.verdict in {"contradict", "partial"}:
            note = finding.evidence_note or finding.advice or ""
            if note and not any(mark in note for mark in _NOT_SEEN):
                sheet.append([
                    _excel_text(finding.text),
                    "按该需求操作",
                    _excel_text(note),
                ])
    if sheet.max_row == 1:
        sheet.append(["", "按需求过一遍", "没有看出明显遗漏"])
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for column, width in {"A": 36, "B": 36, "C": 48}.items():
        sheet.column_dimensions[column].width = width
    for cells in sheet.iter_rows(min_row=2, max_col=3):
        for cell in cells:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()

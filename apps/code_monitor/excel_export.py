from io import BytesIO

from openpyxl import Workbook

from apps.code_monitor.extract import EXCEL_HEADERS, ApiRow


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
            _excel_text(row.response_params),
            _excel_text(row.source_file),
        ])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()

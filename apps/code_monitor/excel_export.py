from io import BytesIO

from openpyxl import Workbook

from apps.code_monitor.extract import EXCEL_HEADERS, ApiRow


def write_api_workbook(rows: list[ApiRow]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "API"
    sheet.append(EXCEL_HEADERS)
    for row in rows:
        sheet.append([
            row.name,
            row.method,
            row.url,
            row.request_params,
            row.response_params,
            row.source_file,
        ])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()

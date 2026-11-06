from io import BytesIO

from openpyxl import load_workbook

from apps.code_monitor.excel_export import write_api_workbook
from apps.code_monitor.extract import EXCEL_HEADERS, ApiRow


def test_workbook_column_order_and_values():
    content = write_api_workbook([
        ApiRow("列表", "GET", "/api/items", "page", "id,name", "src/api/items.js"),
    ])
    sheet = load_workbook(BytesIO(content)).active
    assert [cell.value for cell in sheet[1]] == EXCEL_HEADERS
    assert [cell.value for cell in sheet[2]] == [
        "列表", "GET", "/api/items", "page", "id,name", "src/api/items.js",
    ]


def test_empty_rows_still_have_header():
    sheet = load_workbook(BytesIO(write_api_workbook([]))).active
    assert [cell.value for cell in sheet[1]] == EXCEL_HEADERS
    assert sheet.max_row == 1

# -*- coding: utf-8 -*-
import os
import re
import zipfile
from io import BytesIO

from openpyxl import Workbook
from openpyxl.drawing.image import Image as SheetImage
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

_HEADERS = ("执行编号", "用例", "执行结果", "顺序", "操作", "步骤结果", "说明", "截图")
_UNSAFE = re.compile(r'[\\/:*?"<>|\r\n]+')


def safe_download_name(text, fallback="report"):
    cleaned = _UNSAFE.sub("_", text or "").strip(" .")
    return cleaned or fallback


def pack_report_files(destination, files, notes=None):
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_STORED) as archive:
        for arcname, path in files:
            if path and os.path.isfile(path):
                archive.write(path, arcname)
        for arcname, text in notes or []:
            archive.writestr(arcname, text or "")
    return destination


def _sheet_image(path, kept):
    try:
        from PIL import Image as PillowImage
    except ImportError:
        return None
    try:
        with PillowImage.open(path) as source:
            image = source.convert("RGB")
            image.thumbnail((180, 320))
            buffer = BytesIO()
            image.save(buffer, format="JPEG", quality=70)
            buffer.seek(0)
            buffer.name = "shot.jpg"
    except OSError:
        return None
    kept.append(buffer)
    picture = SheetImage(buffer)
    picture.width = 72
    picture.height = 128
    return picture


def export_executions_xlsx(destination, records):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "执行报告"
    sheet.append(list(_HEADERS))
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(vertical="center")
    kept_images = []
    row_index = 2
    for record in records:
        steps = record.get("steps") or []
        if not steps:
            sheet.append([
                record.get("id") or "",
                record.get("case_name") or "",
                record.get("result") or "",
                "",
                "",
                "",
                record.get("error") or "",
                "",
            ])
            row_index += 1
            continue
        for step in steps:
            sheet.append([
                record.get("id") or "",
                record.get("case_name") or "",
                record.get("result") or "",
                step.get("order") or "",
                step.get("name") or "",
                step.get("status") or "",
                step.get("reason") or "",
                "",
            ])
            image_path = step.get("image_path") or ""
            picture = _sheet_image(image_path, kept_images) if image_path else None
            if picture is not None:
                sheet.add_image(picture, "H%s" % row_index)
                sheet.row_dimensions[row_index].height = 100
            row_index += 1
    widths = (12, 24, 12, 10, 28, 12, 24, 14)
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    workbook.save(destination)
    return destination

# -*- coding: utf-8 -*-
import os
import zipfile
from docx import Document


def write_report_docx(path, steps, video_names, screenrecord_error):
    document = Document()
    document.add_heading("APP 事件链测试报告", level=1)
    if screenrecord_error:
        document.add_paragraph("录屏失败")
        document.add_paragraph(screenrecord_error)
    elif video_names:
        document.add_paragraph("录屏文件")
        for name in video_names:
            document.add_paragraph(os.path.basename(name))
    else:
        document.add_paragraph("录屏失败")
    table = document.add_table(rows=1, cols=6)
    headers = ("顺序", "名称", "类型", "结果", "截图文件名", "失败原因")
    for index, header in enumerate(headers):
        table.rows[0].cells[index].text = header
    for step in steps:
        row = table.add_row().cells
        row[0].text = str(step.get("order") or "")
        row[1].text = step.get("name") or ""
        row[2].text = step.get("type") or ""
        row[3].text = step.get("status") or ""
        row[4].text = os.path.basename(step.get("screenshot") or "")
        row[5].text = step.get("reason") or ""
    document.save(path)
    return path


def playable_video(directory):
    """The first screenrecord often fails and leaves an empty file. Use one that has bytes."""
    best = ""
    best_size = 0
    if not directory or not os.path.isdir(directory):
        return ""
    for name in os.listdir(directory):
        if not name.lower().endswith(".mp4"):
            continue
        path = os.path.join(directory, name)
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        if size > best_size:
            best = path
            best_size = size
    return best


def read_report_steps(path):
    document = Document(path)
    if not document.tables:
        return []
    steps = []
    for row in document.tables[0].rows[1:]:
        cells = [cell.text for cell in row.cells]
        while len(cells) < 6:
            cells.append("")
        steps.append({
            "order": cells[0],
            "name": cells[1],
            "type": cells[2],
            "status": cells[3],
            "screenshot": cells[4],
            "reason": cells[5],
        })
    return steps


def build_result_zip(zip_path, docx_path, screenshot_paths, video_paths):
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(docx_path, "report.docx")
        for shot in screenshot_paths:
            if shot and os.path.isfile(shot):
                archive.write(shot, "screenshots/" + os.path.basename(shot))
        for video in video_paths:
            if video and os.path.isfile(video):
                archive.write(video, os.path.basename(video))
    return zip_path

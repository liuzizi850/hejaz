import os
import zipfile
from docx import Document
from apps.app_automation.recording.report_pack import write_report_docx, build_result_zip


def test_docx_lists_filenames_and_screenrecord_error(tmp_path):
    docx_path = tmp_path / "report.docx"
    write_report_docx(
        str(docx_path),
        [{"order": 1, "name": "点击登录", "type": "click", "status": "passed", "screenshot": "1.png", "reason": ""},
         {"order": 2, "name": "断言", "type": "assert", "status": "failed", "screenshot": "2.png", "reason": "未找到: 欢迎"}],
        [],
        "录屏失败",
    )
    doc = Document(str(docx_path))
    text = "\n".join(p.text for p in doc.paragraphs)
    text += "\n".join(cell.text for table in doc.tables for row in table.rows for cell in row.cells)
    assert "1.png" in text
    assert "2.png" in text
    assert "录屏失败" in text
    assert "欢迎" in text


def test_zip_contains_docx_screenshots_and_videos(tmp_path):
    shot = tmp_path / "1.png"
    shot.write_bytes(b"png")
    video = tmp_path / "video-1.mp4"
    video.write_bytes(b"mp4")
    docx_path = tmp_path / "report.docx"
    write_report_docx(str(docx_path), [], ["video-1.mp4"], "")
    zip_path = tmp_path / "result.zip"
    build_result_zip(str(zip_path), str(docx_path), [str(shot)], [str(video)])
    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
    assert "report.docx" in names
    assert "screenshots/1.png" in names
    assert "video-1.mp4" in names

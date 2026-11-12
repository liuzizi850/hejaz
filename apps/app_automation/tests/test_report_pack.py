import os
import zipfile
from docx import Document
from openpyxl import load_workbook
from PIL import Image
from apps.app_automation.recording.report_pack import (
    write_report_docx,
    build_result_zip,
    read_report_steps,
    playable_video,
)
from apps.app_automation.recording.report_export import export_executions_xlsx, pack_report_files


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


def test_playable_video_skips_empty_recordings(tmp_path):
    (tmp_path / "video-1.mp4").write_bytes(b"")
    (tmp_path / "video-2.mp4").write_bytes(b"")
    (tmp_path / "video-5.mp4").write_bytes(b"mp4-bytes")
    assert os.path.basename(playable_video(str(tmp_path))) == "video-5.mp4"
    assert playable_video(str(tmp_path / "missing")) == ""


def test_read_report_steps_keeps_name_and_screenshot(tmp_path):
    docx_path = tmp_path / "report.docx"
    write_report_docx(
        str(docx_path),
        [{"order": 1, "name": "点击 41%,11%", "type": "click", "status": "passed", "screenshot": str(tmp_path / "1-click.png"), "reason": ""}],
        ["video-1.mp4"],
        "",
    )
    steps = read_report_steps(str(docx_path))
    assert steps[0]["name"] == "点击 41%,11%"
    assert steps[0]["screenshot"] == "1-click.png"
    assert steps[0]["status"] == "passed"


def test_excel_export_keeps_result_operation_and_image(tmp_path):
    image_path = tmp_path / "1-click.png"
    Image.new("RGB", (40, 80), (10, 20, 30)).save(image_path)
    destination = tmp_path / "报告.xlsx"
    export_executions_xlsx(str(destination), [{
        "id": 6,
        "case_name": "测试",
        "result": "失败",
        "error": "",
        "steps": [{
            "order": "1",
            "name": "点击 40%,11%",
            "status": "通过",
            "reason": "",
            "image_path": str(image_path),
        }],
    }])
    sheet = load_workbook(destination).active
    assert sheet["A1"].value == "执行编号"
    assert sheet["C2"].value == "失败"
    assert sheet["E2"].value == "点击 40%,11%"
    assert sheet._images


def test_batch_zip_keeps_report_and_missing_note(tmp_path):
    report = tmp_path / "result.zip"
    report.write_bytes(b"zip-bytes")
    destination = tmp_path / "batch.zip"
    pack_report_files(
        str(destination),
        [("6-测试.zip", str(report))],
        [("7-测试.txt", "这份执行没有报告文件")],
    )
    with zipfile.ZipFile(destination) as archive:
        names = set(archive.namelist())
        assert archive.read("6-测试.zip") == b"zip-bytes"
        assert "这份执行没有报告文件" in archive.read("7-测试.txt").decode("utf-8")
    assert "6-测试.zip" in names


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

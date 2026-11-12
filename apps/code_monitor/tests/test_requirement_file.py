import io

import docx
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from reportlab.pdfgen import canvas

from apps.code_monitor.requirement_file import RequirementFileError, requirement_text_from_upload


def _upload(name, data):
    return SimpleUploadedFile(name, data)


def test_reads_utf8_and_gbk_text():
    utf8 = requirement_text_from_upload(_upload("需求.md", "用户可以用手机号登录".encode("utf-8")))
    gbk = requirement_text_from_upload(_upload("需求.txt", "密码连续错误 5 次后锁定".encode("gbk")))
    assert utf8 == "用户可以用手机号登录"
    assert gbk == "密码连续错误 5 次后锁定"


def test_reads_docx_paragraphs_and_tables():
    document = docx.Document()
    document.add_paragraph("用户可以用手机号登录")
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "锁定"
    table.rows[0].cells[1].text = "连续错误 5 次"
    buffer = io.BytesIO()
    document.save(buffer)
    text = requirement_text_from_upload(_upload("需求.docx", buffer.getvalue()))
    assert "用户可以用手机号登录" in text
    assert "锁定 | 连续错误 5 次" in text


def test_reads_pdf_text():
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.drawString(72, 72, "phone login")
    pdf.save()
    text = requirement_text_from_upload(_upload("需求.pdf", buffer.getvalue()))
    assert "phone login" in text


def test_rejects_unsupported_empty_and_oversized_files():
    with pytest.raises(RequirementFileError, match="只支持"):
        requirement_text_from_upload(_upload("需求.doc", b"binary"))
    with pytest.raises(RequirementFileError, match="没有可读文本"):
        requirement_text_from_upload(_upload("需求.txt", b"   \n"))
    with pytest.raises(RequirementFileError, match="无法读取"):
        requirement_text_from_upload(_upload("需求.pdf", b"not-a-pdf"))
    huge = SimpleUploadedFile("需求.txt", b"x" * (10 * 1024 * 1024 + 1))
    with pytest.raises(RequirementFileError, match="10MB"):
        requirement_text_from_upload(huge)

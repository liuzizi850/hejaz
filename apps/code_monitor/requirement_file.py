import io
from pathlib import Path

MAX_REQUIREMENT_FILE_BYTES = 10 * 1024 * 1024
_ALLOWED_SUFFIXES = {".txt", ".md", ".pdf", ".docx"}


class RequirementFileError(Exception):
    pass


def requirement_text_from_upload(uploaded) -> str:
    name = getattr(uploaded, "name", "") or ""
    suffix = Path(name).suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise RequirementFileError("需求文件只支持 txt、md、pdf、docx")
    size = getattr(uploaded, "size", None)
    if size is not None and size > MAX_REQUIREMENT_FILE_BYTES:
        raise RequirementFileError("需求文件不能超过 10MB")
    data = uploaded.read(MAX_REQUIREMENT_FILE_BYTES + 1)
    if len(data) > MAX_REQUIREMENT_FILE_BYTES:
        raise RequirementFileError("需求文件不能超过 10MB")
    if suffix in {".txt", ".md"}:
        text = _text_from_bytes(data)
    elif suffix == ".docx":
        text = _text_from_docx(data)
    else:
        text = _text_from_pdf(data)
    text = text.strip()
    if not text:
        raise RequirementFileError("需求文件里没有可读文本")
    return text


def _text_from_bytes(data: bytes) -> str:
    if not data.strip():
        return ""
    for encoding in ("utf-8-sig", "gbk"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise RequirementFileError("需求文件无法读取")


def _text_from_docx(data: bytes) -> str:
    try:
        import docx
    except ImportError as exc:
        raise RequirementFileError("需求文件无法读取") from exc
    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:
        raise RequirementFileError("需求文件无法读取") from exc
    parts = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = []
            for cell in row.cells:
                cell_text = cell.text.strip()
                if cell_text and cell_text not in cells:
                    cells.append(cell_text)
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def _text_from_pdf(data: bytes) -> str:
    try:
        from PyPDF2 import PdfReader
    except ImportError:
        from PyPDF2 import PdfFileReader as PdfReader
    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as exc:
        raise RequirementFileError("需求文件无法读取") from exc

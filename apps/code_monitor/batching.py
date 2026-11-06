from dataclasses import dataclass
from pathlib import Path

from apps.code_monitor.screening import resolved_path_is_inside

MAX_BATCH_CHARS = 60000


@dataclass
class FileChunk:
    source_file: str
    text: str


def render_batch(chunks: list[FileChunk]) -> str:
    parts = [f"文件: {chunk.source_file}\n{chunk.text}" for chunk in chunks]
    return "\n\n".join(parts)


def split_into_batches(files: list[Path], root: Path, max_chars: int = MAX_BATCH_CHARS) -> list[list[FileChunk]]:
    if max_chars <= 0:
        raise ValueError("批次字符预算必须大于 0")
    chunks = []
    for path in files:
        if not resolved_path_is_inside(path, root):
            continue
        relative = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        chunks.extend(_slice_text(relative, text, _body_budget(relative, max_chars)))
    return _pack(chunks, max_chars)


def _body_budget(source_file: str, max_chars: int) -> int:
    overhead = len(f"文件: {source_file}\n")
    if overhead < max_chars:
        return max_chars - overhead
    return max_chars


def _slice_text(source_file: str, text: str, max_chars: int) -> list[FileChunk]:
    if max_chars <= 0:
        raise ValueError("批次字符预算必须大于 0")
    if len(text) <= max_chars:
        return [FileChunk(source_file, text)] if text else []
    pieces = []
    buf = []
    size = 0
    for line in text.splitlines(keepends=True):
        start = 0
        while start < len(line):
            room = max_chars - size
            if room <= 0 and buf:
                pieces.append(FileChunk(source_file, "".join(buf)))
                buf = []
                size = 0
                room = max_chars
            take = line[start:start + room]
            if not take:
                raise ValueError("批次字符预算必须大于 0")
            buf.append(take)
            size += len(take)
            start += len(take)
            if size >= max_chars:
                pieces.append(FileChunk(source_file, "".join(buf)))
                buf = []
                size = 0
    if buf:
        pieces.append(FileChunk(source_file, "".join(buf)))
    return pieces


def _pack(chunks: list[FileChunk], max_chars: int) -> list[list[FileChunk]]:
    if max_chars <= 0:
        raise ValueError("批次字符预算必须大于 0")
    batches = []
    current = []
    for chunk in chunks:
        if current and len(render_batch(current + [chunk])) > max_chars:
            batches.append(current)
            current = []
        current.append(chunk)
    if current:
        batches.append(current)
    return batches

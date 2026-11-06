from dataclasses import dataclass
from pathlib import Path

MAX_BATCH_CHARS = 60000


@dataclass
class FileChunk:
    source_file: str
    text: str


def split_into_batches(files: list[Path], root: Path, max_chars: int = MAX_BATCH_CHARS) -> list[list[FileChunk]]:
    chunks = []
    for path in files:
        relative = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        chunks.extend(_slice_text(relative, text, max_chars))
    return _pack(chunks, max_chars)


def _slice_text(source_file: str, text: str, max_chars: int) -> list[FileChunk]:
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
    batches = []
    current = []
    size = 0
    for chunk in chunks:
        if current and size + len(chunk.text) > max_chars:
            batches.append(current)
            current = []
            size = 0
        current.append(chunk)
        size += len(chunk.text)
    if current:
        batches.append(current)
    return batches

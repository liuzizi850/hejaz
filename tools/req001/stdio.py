# -*- coding: utf-8 -*-
"""Encoding-safe stdio helpers for Windows consoles (e.g. cp1252)."""
from __future__ import annotations

import sys
from typing import Any, Optional, TextIO


def configure_stdio() -> None:
    """Best-effort: keep prints from crashing on a legacy Windows code page.

    Prefer UTF-8 when the stream allows it; otherwise keep the current
    encoding and replace unencodable characters. Never raises.
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None or not hasattr(stream, "reconfigure"):
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            try:
                stream.reconfigure(errors="replace")
            except Exception:
                pass


def safe_print(*args: Any, file: Optional[TextIO] = None, sep: str = " ", end: str = "\n", flush: bool = False) -> None:
    """Print text without raising UnicodeEncodeError on cp1252/ascii stdout."""
    stream = sys.stdout if file is None else file
    text = sep.join(str(a) for a in args) + end
    try:
        stream.write(text)
    except UnicodeEncodeError:
        enc = getattr(stream, "encoding", None) or "utf-8"
        raw = text.encode(enc, errors="replace")
        written = False
        try:
            stream.write(raw.decode(enc, errors="replace"))
            written = True
        except Exception:
            buf = getattr(stream, "buffer", None)
            if buf is not None:
                try:
                    buf.write(raw)
                    written = True
                except Exception:
                    pass
        if not written:
            fallback = getattr(sys, "__stdout__", None)
            buf = getattr(fallback, "buffer", None) if fallback is not None else None
            if buf is not None:
                try:
                    buf.write(raw)
                except Exception:
                    pass
    if flush:
        try:
            stream.flush()
        except Exception:
            pass

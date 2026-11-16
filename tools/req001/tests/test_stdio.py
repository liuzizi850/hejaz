# -*- coding: utf-8 -*-
import io

from tools.req001.stdio import configure_stdio, safe_print


def test_safe_print_under_cp1252_strict_does_not_raise():
    buf = io.BytesIO()
    stream = io.TextIOWrapper(buf, encoding="cp1252", errors="strict", newline="\n")
    safe_print("模拟器就绪: 测试中文与夹具失败", file=stream, flush=True)
    data = buf.getvalue()
    assert len(data) > 0
    # Unencodable characters are replaced, but the call must not raise.
    decoded = data.decode("cp1252", errors="replace")
    assert ":" in decoded or "?" in decoded or "就绪" in decoded


def test_safe_print_under_ascii_stdout_exits_clean():
    buf = io.BytesIO()
    stream = io.TextIOWrapper(buf, encoding="ascii", errors="strict", newline="\n")
    safe_print("报告已写出: 通过 / 失败", file=stream, flush=True)
    assert len(buf.getvalue()) > 0


def test_configure_stdio_does_not_raise():
    configure_stdio()

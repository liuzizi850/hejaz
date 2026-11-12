# -*- coding: utf-8 -*-
"""CLI entry: python tools/req001/ensure_emulator.py"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from tools.req001.stdio import configure_stdio  # noqa: E402
from tools.req001.emulator import main  # noqa: E402

configure_stdio()

if __name__ == "__main__":
    raise SystemExit(main())

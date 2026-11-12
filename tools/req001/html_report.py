# -*- coding: utf-8 -*-
"""T5: self-contained local HTML report (no Allure required)."""
from __future__ import annotations

import html
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional, Sequence


def _now_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


@dataclass
class CaseResult:
    case_id: str
    name: str
    status: str  # "pass" | "fail"
    failure_reason: str = ""
    screenshots: List[str] = field(default_factory=list)
    steps: List[str] = field(default_factory=list)


@dataclass
class RunReport:
    run_id: str
    device_serial: str
    app_package: str
    app_source: str  # "preinstalled_calculator" | "fallback_apk" | "unknown"
    cases: List[CaseResult] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""
    notes: List[str] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.cases if c.status == "pass")

    @property
    def failed(self) -> int:
        return sum(1 for c in self.cases if c.status == "fail")


APP_SOURCE_LABELS = {
    "preinstalled_calculator": "预装计算器（运行时探测命中）",
    "fallback_apk": "仓库备选 APK（未探测到预装计算器，已安装）",
    "unknown": "未知",
}


def _copy_screenshots(case: CaseResult, dest_dir: Path) -> List[str]:
    """Copy screenshots into the report folder; return relative POSIX paths."""
    rels: List[str] = []
    case_dir = dest_dir / "screenshots" / _safe_name(case.case_id or case.name or "case")
    for index, raw in enumerate(case.screenshots, start=1):
        src = Path(raw)
        if not src.is_file():
            continue
        case_dir.mkdir(parents=True, exist_ok=True)
        name = f"{index:02d}_{src.name}"
        target = case_dir / name
        if src.resolve() != target.resolve():
            shutil.copy2(src, target)
        rels.append(target.relative_to(dest_dir).as_posix())
    return rels


def _safe_name(value: str) -> str:
    keep = []
    for ch in value:
        keep.append(ch if ch.isalnum() or ch in {"-", "_", "."} else "_")
    return "".join(keep)[:80] or "case"


def _status_badge(status: str) -> str:
    if status == "pass":
        return '<span class="badge pass">通过</span>'
    return '<span class="badge fail">失败</span>'


def render_html(report: RunReport, screenshot_rels: Sequence[Sequence[str]]) -> str:
    rows = []
    for case, rels in zip(report.cases, screenshot_rels):
        shots = []
        if not rels:
            shots.append("<p class='muted'>（无截图）</p>")
        for rel in rels:
            shots.append(
                f'<figure><img src="{html.escape(rel)}" alt="{html.escape(case.case_id)} 截图">'
                f"<figcaption>{html.escape(rel)}</figcaption></figure>"
            )
        reason = html.escape(case.failure_reason) if case.failure_reason else "—"
        step_html = ""
        if case.steps:
            items = "".join(f"<li>{html.escape(s)}</li>" for s in case.steps)
            step_html = f"<ol class='steps'>{items}</ol>"
        rows.append(
            f"""
            <article class="case {html.escape(case.status)}" id="{html.escape(case.case_id)}">
              <header>
                <h2>{html.escape(case.case_id)} · {html.escape(case.name)}</h2>
                {_status_badge(case.status)}
              </header>
              <p><strong>失败原因：</strong>{reason}</p>
              {step_html}
              <div class="shots">{''.join(shots)}</div>
            </article>
            """
        )

    source_label = APP_SOURCE_LABELS.get(report.app_source, report.app_source or "未知")
    body = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>REQ-001 试跑报告 {html.escape(report.run_id)}</title>
  <style>
    :root {{
      --bg: #f5f7fb; --card: #fff; --ink: #1c2333; --muted: #5b657a;
      --pass: #0f7b3a; --pass-bg: #e8f8ee; --fail: #b42318; --fail-bg: #fdecea;
      --line: #e3e8f2;
    }}
    body {{ font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
           margin: 0; background: var(--bg); color: var(--ink); }}
    main {{ max-width: 960px; margin: 0 auto; padding: 24px 16px 48px; }}
    h1 {{ margin: 0 0 8px; font-size: 24px; }}
    .summary, .case {{ background: var(--card); border: 1px solid var(--line);
                       border-radius: 12px; padding: 16px 20px; margin: 16px 0; }}
    .grid {{ display: grid; grid-template-columns: 160px 1fr; gap: 6px 12px; }}
    .muted, figcaption {{ color: var(--muted); font-size: 12px; }}
    .badge {{ display: inline-block; border-radius: 999px; padding: 2px 10px;
              font-size: 13px; font-weight: 600; }}
    .badge.pass {{ background: var(--pass-bg); color: var(--pass); }}
    .badge.fail {{ background: var(--fail-bg); color: var(--fail); }}
    .case header {{ display: flex; justify-content: space-between; align-items: center; gap: 12px; }}
    .case h2 {{ margin: 0; font-size: 18px; }}
    .case.fail {{ border-left: 4px solid var(--fail); }}
    .case.pass {{ border-left: 4px solid var(--pass); }}
    .shots {{ display: flex; flex-wrap: wrap; gap: 12px; }}
    figure {{ margin: 0; }}
    img {{ max-width: 280px; max-height: 480px; border: 1px solid var(--line); border-radius: 8px; }}
    ol.steps {{ padding-left: 20px; }}
  </style>
</head>
<body>
  <main>
    <h1>REQ-001 本地试跑报告</h1>
    <p class="muted">用浏览器直接打开本文件即可查看，不依赖 Allure 或其他 CLI。</p>
    <section class="summary">
      <h2>运行摘要</h2>
      <div class="grid">
        <div>运行编号</div><div>{html.escape(report.run_id)}</div>
        <div>开始时间</div><div>{html.escape(report.started_at or "—")}</div>
        <div>结束时间</div><div>{html.escape(report.finished_at or "—")}</div>
        <div>设备序列号</div><div>{html.escape(report.device_serial or "—")}</div>
        <div>实际包名</div><div>{html.escape(report.app_package or "—")}</div>
        <div>应用来源</div><div>{html.escape(source_label)}</div>
        <div>结果统计</div><div>通过 {report.passed} / 失败 {report.failed} / 共 {len(report.cases)}</div>
      </div>
      {"<ul>" + "".join(f"<li>{html.escape(n)}</li>" for n in report.notes) + "</ul>" if report.notes else ""}
    </section>
    {''.join(rows)}
  </main>
</body>
</html>
"""
    return body


def write_report(report: RunReport, output_dir: Path) -> Path:
    """Write index.html and copy screenshots. Returns the index.html path."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rels: List[List[str]] = []
    for case in report.cases:
        rels.append(_copy_screenshots(case, output_dir))
        # Keep original paths in the dataclass; HTML uses copied relative paths.
    index = output_dir / "index.html"
    index.write_text(render_html(report, rels), encoding="utf-8")
    return index


def new_run_id() -> str:
    return _now_id()

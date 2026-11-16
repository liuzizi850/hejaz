#!/usr/bin/env python3
"""Advisory-only AI review of staged changes for business/requirement bugs.

Always exits 0 so a review never blocks the commit.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

DIFF_CHAR_LIMIT = 80_000
DOCS_CHAR_LIMIT = 24_000
TIMEOUT_SECONDS = 90
SKIP_DOC_NAMES = {"key.py", ".env", ".env.bak"}
SKIP_DOC_SUFFIXES = {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".zip", ".exe"}

REPO_ROOT = Path(__file__).resolve().parents[1]


def configure_stdio() -> None:
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def say(message: str) -> None:
    try:
        print(message, flush=True)
    except UnicodeEncodeError:
        data = (message + chr(10)).encode("utf-8", errors="replace")
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()


def run_git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "git failed").strip())
    return result.stdout


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key:
            values[key] = value
    return values


def load_settings() -> dict[str, str]:
    settings: dict[str, str] = {}
    candidates = [
        Path.home() / ".commit-review.env",
        Path.home() / ".config" / "commit-review.env",
        REPO_ROOT / ".commit-review.env",
        REPO_ROOT / ".env",
    ]
    for path in candidates:
        settings.update(parse_env_file(path))
    for key, value in os.environ.items():
        if value:
            settings[key] = value
    return settings


def resolve_provider(settings: dict[str, str]) -> tuple[str, str, str] | None:
    """Return (base_url, api_key, model) for an OpenAI-compatible API."""
    custom_key = settings.get("COMMIT_REVIEW_API_KEY")
    if custom_key:
        base = settings.get("COMMIT_REVIEW_BASE_URL") or settings.get("OPENAI_BASE_URL") or "https://api.openai.com/v1"
        model = settings.get("COMMIT_REVIEW_MODEL") or settings.get("OPENAI_MODEL") or "gpt-4o-mini"
        return base, custom_key, model

    if settings.get("DEEPSEEK_API_KEY"):
        base = settings.get("COMMIT_REVIEW_BASE_URL") or "https://api.deepseek.com"
        model = settings.get("COMMIT_REVIEW_MODEL") or "deepseek-chat"
        return base, settings["DEEPSEEK_API_KEY"], model

    if settings.get("OPENAI_API_KEY"):
        base = settings.get("OPENAI_BASE_URL") or settings.get("COMMIT_REVIEW_BASE_URL") or "https://api.openai.com/v1"
        model = settings.get("OPENAI_MODEL") or settings.get("COMMIT_REVIEW_MODEL") or "gpt-4o-mini"
        return base, settings["OPENAI_API_KEY"], model

    if settings.get("DASHSCOPE_API_KEY"):
        base = settings.get("COMMIT_REVIEW_BASE_URL") or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        model = settings.get("COMMIT_REVIEW_MODEL") or "qwen-plus"
        return base, settings["DASHSCOPE_API_KEY"], model

    return None


def redact(text: str) -> str:
    patterns = [
        (re.compile(r"(?i)(api[_-]?key|token|secret|password|authorization)\s*[:=]\s*([^\s\"']+)", re.I), r"\1=[REDACTED]"),
        (re.compile(r"(?i)bearer\s+[a-z0-9._\-]+"), "Bearer [REDACTED]"),
        (re.compile(r"\bsk-[A-Za-z0-9]{8,}\b"), "[REDACTED]"),
    ]
    for pattern, replacement in patterns:
        text = pattern.sub(replacement, text)
    return text


def staged_files() -> list[str]:
    output = run_git("diff", "--cached", "--name-only", "-z")
    return [name for name in output.split("\0") if name]


def staged_diff() -> str:
    diff = run_git("diff", "--cached", "--unified=3", "--no-color")
    diff = redact(diff)
    if len(diff) > DIFF_CHAR_LIMIT:
        return diff[:DIFF_CHAR_LIMIT] + "\n\n[diff truncated]\n"
    return diff


def should_include_doc(path: Path, changed: list[str]) -> bool:
    if path.name in SKIP_DOC_NAMES or path.suffix.lower() in SKIP_DOC_SUFFIXES:
        return False
    if path.suffix.lower() not in {".md", ".txt"}:
        return False
    rel = path.relative_to(REPO_ROOT).as_posix().lower()
    joined = " ".join(changed).lower()
    keywords = []
    if any(part in joined for part in ("recording", "event_chain", "app_automation", "replay", "touch")):
        keywords.extend(["event-chain", "recording", "replay"])
    if any(part in joined for part in ("code_monitor", "code-monitor")):
        keywords.extend(["code-monitor", "code_monitor"])
    if keywords:
        return any(key in rel for key in keywords)
    # If we cannot map the change, prefer short design specs over long plans.
    return "docs/superpowers/specs/" in rel


def collect_docs(changed: list[str]) -> str:
    docs_root = REPO_ROOT / "docs"
    if not docs_root.is_dir():
        return ""
    pieces: list[str] = []
    used = 0
    files = sorted(docs_root.rglob("*"), key=lambda p: (0 if "specs" in p.parts else 1, p.stat().st_size if p.is_file() else 0))
    for path in files:
        if not path.is_file() or not should_include_doc(path, changed):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        chunk = f"## {rel}\n{text.strip()}\n"
        if used + len(chunk) > DOCS_CHAR_LIMIT:
            remain = DOCS_CHAR_LIMIT - used
            if remain > 200:
                pieces.append(chunk[:remain] + "\n[doc truncated]\n")
            break
        pieces.append(chunk)
        used += len(chunk)
    return "\n".join(pieces)


def normalize_base(base: str) -> str:
    base = base.rstrip("/")
    if not base.endswith("/v1"):
        # DeepSeek official root is https://api.deepseek.com and also accepts /v1
        if "api.deepseek.com" in base and not base.endswith("/v1"):
            base = base + "/v1"
    return base


def https_endpoint(base: str) -> tuple[str, int, str]:
    parsed = urlparse(normalize_base(base) + "/chat/completions")
    if parsed.scheme != "https" or not parsed.hostname:
        raise RuntimeError("模型地址必须是 https，且不能是 file 或其他协议")
    if parsed.username or parsed.password:
        raise RuntimeError("模型地址不能包含账号信息")
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    return parsed.hostname, parsed.port or 443, path


def request_review(base: str, api_key: str, model: str, prompt: str) -> str:
    host, port, path = https_endpoint(base)
    payload = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是项目业务评审助手。根据暂存的代码改动和提供的需求文档，"
                    "只查找需求理解偏差、业务流程错误、遗漏的业务规则或边界情况。"
                    "不要评价代码风格，不要重复安全扫描能发现的问题，除非它会直接导致业务错误。"
                    "用简体中文回复，先给结论，再列 3 到 8 条具体意见；每条指出文件或行为，并说明为何可能不符合需求。"
                    "如果没有明显业务问题，明确说本次未见明显业务风险，并最多补一条可选注意点。"
                    "这些意见不会拦住提交，保持克制，不要夸大。"
                ),
            },
            {"role": "user", "content": prompt},
        ],
    }
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    try:
        # Python 3.12 会校验证书。这条规则只针对 3.4.3 之前的默认行为。
        connection = http.client.HTTPSConnection(  # nosemgrep: python.lang.security.audit.httpsconnection-detected.httpsconnection-detected
            host, port, timeout=TIMEOUT_SECONDS
        )
        try:
            connection.request("POST", path, body=data, headers=headers)
            response = connection.getresponse()
            raw = response.read()
        finally:
            connection.close()
        if response.status >= 400:
            detail = raw.decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"模型接口返回 HTTP {response.status}: {detail}")
        body = json.loads(raw.decode("utf-8"))
    except RuntimeError:
        raise
    except Exception as exc:  # noqa: BLE001 — advisory hook must never raise to git
        raise RuntimeError(f"调用模型失败: {exc}") from exc

    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("模型返回格式无法解析") from exc
    return str(content).strip() or "模型没有返回评审内容。"


def main() -> int:
    configure_stdio()
    header = "[业务评审] 以下仅为意见，不会拦住本次提交。"
    try:
        changed = staged_files()
        if not changed:
            say("[业务评审] 没有暂存改动，已跳过。")
            return 0

        settings = load_settings()
        provider = resolve_provider(settings)
        if provider is None:
            say(
                "[业务评审] 未配置模型密钥，已跳过。"
                "请设置环境变量 DEEPSEEK_API_KEY、OPENAI_API_KEY，或 DASHSCOPE_API_KEY，"
                "或在用户目录创建 .commit-review.env。本次提交不会被拦住。"
            )
            return 0

        diff = staged_diff()
        if not diff.strip():
            say("[业务评审] 暂存区没有可检查的文本差异，已跳过。")
            return 0

        docs = collect_docs(changed)
        prompt = (
            "本次暂存文件:\n- "
            + "\n- ".join(changed[:200])
            + "\n\n需求文档:\n"
            + (docs or "（本次没有匹配到相关需求文档，请只根据代码改动判断业务风险。）")
            + "\n\n暂存差异:\n"
            + diff
        )

        base, api_key, model = provider
        say(header)
        say(f"[业务评审] 正在使用模型 {model} 检查本次改动…")
        review = request_review(base, api_key, model, prompt)
        say(review)
    except Exception as exc:  # noqa: BLE001
        say(f"[业务评审] 已跳过：{exc}。本次提交不会被拦住。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

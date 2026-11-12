# -*- coding: utf-8 -*-
"""Minimal RAGFlow HTTP client for TestHub's AI reviewer."""
import re
from urllib.parse import urlparse

import requests

_IMAGE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_MAX_REFERENCE_CHUNKS = 20
_MAX_REFERENCE_CONTENT = 8000


class RagflowError(Exception):
    def __init__(self, message, status_code=400, detail=None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.detail = detail


def normalize_base_url(api_url):
    """Accept either http://host:9380 or http://host:9380/api/v1."""
    url = (api_url or "").strip().rstrip("/")
    if not url:
        raise RagflowError("API URL 不能为空")
    if url.endswith("/api/v1"):
        return url
    return f"{url}/api/v1"


def _headers(api_key):
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _parse_body(response):
    try:
        return response.json()
    except ValueError as exc:
        raise RagflowError(
            f"RAGFlow 返回了无法解析的响应: HTTP {response.status_code}",
            status_code=response.status_code,
            detail=response.text,
        ) from exc


def _raise_for_body(response, body, default_message):
    if isinstance(body, dict) and body.get("code") not in (0, None):
        raise RagflowError(
            body.get("message") or default_message,
            status_code=400 if response.status_code < 400 else response.status_code,
            detail=body,
        )
    if response.status_code >= 400:
        message = default_message
        if isinstance(body, dict):
            message = body.get("message") or body.get("error") or default_message
        raise RagflowError(
            f"{message}: HTTP {response.status_code}",
            status_code=response.status_code,
            detail=body if body else response.text,
        )


def list_chats(api_url, api_key, chat_id=None, timeout=30):
    base = normalize_base_url(api_url)
    params = {"page": 1, "page_size": 50}
    if chat_id:
        params["id"] = chat_id
    try:
        response = requests.get(
            f"{base}/chats",
            headers=_headers(api_key),
            params=params,
            timeout=timeout,
        )
    except requests.exceptions.Timeout as exc:
        raise RagflowError("连接超时，请检查 API URL 是否正确", status_code=408) from exc
    except requests.exceptions.RequestException as exc:
        raise RagflowError(f"连接错误: {exc}", status_code=400) from exc

    body = _parse_body(response)
    _raise_for_body(response, body, "无法列出 RAGFlow Chat Assistant")
    data = body.get("data") if isinstance(body, dict) else None
    if isinstance(data, dict):
        return data.get("chats") or []
    if isinstance(data, list):
        return data
    return []


def chat_completion(api_url, api_key, question, chat_id=None, session_id=None, timeout=60):
    """Call RAGFlow 1.0 POST /api/v1/chat/completions in non-streaming mode."""
    base = normalize_base_url(api_url)
    payload = {
        "question": question,
        "stream": False,
    }
    if chat_id:
        payload["chat_id"] = chat_id
    if session_id:
        payload["session_id"] = session_id

    try:
        response = requests.post(
            f"{base}/chat/completions",
            headers=_headers(api_key),
            json=payload,
            timeout=timeout,
        )
    except requests.exceptions.Timeout as exc:
        raise RagflowError("API 请求超时", status_code=408) from exc
    except requests.exceptions.RequestException as exc:
        raise RagflowError(f"API 请求失败: {exc}", status_code=500) from exc

    body = _parse_body(response)
    _raise_for_body(response, body, "RAGFlow API 错误")
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        raise RagflowError("RAGFlow 返回了意外的响应格式", status_code=500, detail=body)
    return data


def normalize_reference(reference):
    """Keep the fields the chat UI needs to show a cited source and its page."""
    normalized = []
    for index, chunk in enumerate(_reference_chunks(reference)[:_MAX_REFERENCE_CHUNKS]):
        if not isinstance(chunk, dict):
            continue
        content = str(chunk.get("content") or chunk.get("content_with_weight") or "").strip()
        if len(content) > _MAX_REFERENCE_CONTENT:
            content = content[:_MAX_REFERENCE_CONTENT]
        document_name = str(
            chunk.get("document_name") or chunk.get("docnm_kwd") or chunk.get("doc_name") or ""
        ).strip()
        image_id = str(chunk.get("image_id") or chunk.get("img_id") or "").strip()
        if image_id and not _IMAGE_ID_RE.match(image_id):
            image_id = ""
        item = {
            "index": index,
            "content": content,
            "document_id": str(chunk.get("document_id") or chunk.get("doc_id") or ""),
            "document_name": document_name,
            "dataset_id": str(chunk.get("dataset_id") or chunk.get("kb_id") or ""),
            "image_id": image_id,
            "page": _first_page(chunk.get("positions") or chunk.get("position")),
        }
        if content or document_name or image_id:
            normalized.append(item)
    return normalized


def fetch_chunk_image(api_url, api_key, image_id, timeout=30):
    """Download a knowledge-base page snapshot. Returns (bytes, media_type)."""
    if not _IMAGE_ID_RE.match(image_id or ""):
        raise RagflowError("无效的原文图片标识", status_code=400)
    base = normalize_base_url(api_url)
    origin = base[: -len("/api/v1")] if base.endswith("/api/v1") else base
    allowed_host = urlparse(base).netloc
    candidates = [
        f"{base}/documents/images/{image_id}",
        f"{origin}/v1/document/image/{image_id}",
    ]
    for url in candidates:
        try:
            response = requests.get(
                url,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=timeout,
            )
        except requests.exceptions.Timeout as exc:
            raise RagflowError("原文图片请求超时", status_code=408) from exc
        except requests.exceptions.RequestException:
            continue
        if urlparse(getattr(response, "url", "") or url).netloc != allowed_host:
            continue
        media_type = _image_media_type(
            response.content or b"",
            response.headers.get("Content-Type") or "",
        )
        if response.status_code == 200 and media_type:
            return response.content, media_type
    raise RagflowError("无法获取知识库原文图片", status_code=404)


def _reference_chunks(reference):
    if isinstance(reference, list):
        return reference
    if isinstance(reference, dict):
        chunks = reference.get("chunks")
        if isinstance(chunks, list):
            return chunks
    return []


def _first_page(positions):
    if not isinstance(positions, list) or not positions:
        return None
    first = positions[0]
    if isinstance(first, (list, tuple)) and first:
        raw = first[0]
    elif isinstance(first, int):
        raw = first
    else:
        return None
    try:
        page = int(raw)
    except (TypeError, ValueError):
        return None
    if page < 0:
        return None
    return 1 if page == 0 else page


def _image_media_type(content, content_type):
    if not content:
        return ""
    media = (content_type or "").split(";")[0].strip().lower()
    if media.startswith("image/"):
        return media
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG"):
        return "image/png"
    if content.startswith(b"GIF8"):
        return "image/gif"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image/webp"
    return ""


def is_session_error(error):
    text = " ".join(
        str(part)
        for part in (getattr(error, "message", ""), getattr(error, "detail", ""))
        if part
    ).lower()
    return "session" in text

import json

import pytest
from rest_framework.test import APIClient

from apps.requirement_analysis.models import (
    AIModelConfig,
    RequirementDocument,
    RequirementDraft,
    RequirementQualityReview,
)
from apps.requirement_analysis.quality_review import normalize_review
from apps.requirement_analysis.requirement_writer import (
    EMPTY_MARK,
    RequirementWriteError,
    normalize_draft,
    parse_model_payload,
    prepare_source,
    write_requirement,
)
from apps.users.models import User

pytestmark = pytest.mark.django_db

SAMPLE = "用户使用手机号和验证码登录。验证码 5 分钟内有效，连续错误 3 次锁定 30 分钟。"
MARKDOWN = (
    "# 登录\n\n## 背景与目标\n用户使用手机号和验证码登录。\n\n"
    "## 验收标准\n1. 条件：已注册；操作：提交正确验证码；预期：进入首页。\n"
)


def _client(username="writer"):
    user = User.objects.create_user(username=username, password="pass123456")
    client = APIClient()
    client.force_authenticate(user)
    return client, user


def _config(user, role="writer"):
    return AIModelConfig.objects.create(
        name=f"{role}-{user.username}",
        model_type="other",
        role=role,
        base_url="https://example.com/v1",
        model_name=f"fake-{role}",
        created_by=user,
        is_active=True,
    )


def _payload():
    return {
        "sections": {
            "background": "用户用手机号登录",
            "角色与权限": "未注册用户可以获取验证码",
            "preconditions": "",
            "main_flow": "输入手机号后获取验证码",
            "exceptions": "验证码错误时登录失败",
            "state_changes": "",
            "inputs_outputs": "输入手机号，返回是否登录成功",
        },
        "acceptance_criteria": [
            {"condition": "已注册手机号", "action": "提交正确验证码", "expected": "进入首页"},
            {"condition": "验证码过期", "action": "", "expected": ""},
        ],
        "open_questions": [
            {"topic": "锁定", "missing": "没有写解锁条件", "impact": "不补上就无法判定何时恢复"},
        ],
    }


def _written(title="登录"):
    return normalize_draft(_payload(), title)


def test_parse_and_keep_only_complete_criteria():
    raw = "```json\n" + json.dumps(_payload(), ensure_ascii=False) + "\n```"
    draft = normalize_draft(parse_model_payload(raw), "登录")
    assert draft["sections"]["roles"] == "未注册用户可以获取验证码"
    assert draft["sections"]["preconditions"] == EMPTY_MARK
    assert draft["sections"]["state_changes"] == EMPTY_MARK
    assert len(draft["acceptance_criteria"]) == 1
    assert draft["acceptance_criteria"][0]["id"] == "A1"
    assert draft["acceptance_criteria"][0]["expected"] == "进入首页"
    assert any(item["topic"] == "验证码过期" for item in draft["open_questions"])
    assert "进入首页" in draft["document_markdown"]
    assert "## 待确认" in draft["document_markdown"]
    assert draft["gaps_unlisted"] is False


def test_unspecified_sections_without_questions_are_flagged():
    draft = normalize_draft({"sections": {}, "acceptance_criteria": [], "open_questions": []}, "空")
    assert all(value == EMPTY_MARK for value in draft["sections"].values())
    assert draft["gaps_unlisted"] is True
    assert "未发现需要单列的待确认项" in draft["document_markdown"]


def test_unparseable_model_output():
    with pytest.raises(RequirementWriteError):
        parse_model_payload("这不是需求文档")


def test_short_source_rejected():
    with pytest.raises(RequirementWriteError):
        prepare_source("太短")


def test_write_retries_then_returns_document(monkeypatch):
    calls = {"count": 0}

    def fake_call(config, text, title):
        calls["count"] += 1
        if calls["count"] == 1:
            return "不是 JSON"
        return json.dumps(_payload(), ensure_ascii=False)

    monkeypatch.setattr("apps.requirement_analysis.requirement_writer._call_model", fake_call)
    draft = write_requirement(object(), SAMPLE, "登录")
    assert calls["count"] == 2
    assert draft["acceptance_criteria"][0]["expected"] == "进入首页"


def test_draft_requires_text():
    client, user = _client()
    _config(user)
    response = client.post("/api/requirement-analysis/drafts/", {"title": "登录"}, format="json")
    assert response.status_code == 400
    assert RequirementDraft.objects.count() == 0


def test_draft_requires_login():
    response = APIClient().post(
        "/api/requirement-analysis/drafts/",
        {"title": "登录", "text": SAMPLE},
        format="json",
    )
    assert response.status_code == 401


def test_draft_prefers_writer_and_hides_source_in_list(monkeypatch):
    client, user = _client()
    _config(user, role="reviewer")
    _config(user, role="writer")
    seen = {}

    def fake(config, text, title):
        seen["role"] = config.role
        assert "验证码" in text
        return _written(title)

    monkeypatch.setattr("apps.requirement_analysis.requirement_writer_views.write_requirement", fake)
    response = client.post(
        "/api/requirement-analysis/drafts/",
        {"title": "登录", "text": SAMPLE},
        format="json",
    )
    assert response.status_code == 201
    body = response.json()
    assert seen["role"] == "writer"
    assert body["model_name"] == "fake-writer"
    assert body["acceptance_count"] == 1
    assert "source_text" in body
    assert RequirementDocument.objects.count() == 0

    listed = client.get("/api/requirement-analysis/drafts/")
    row = listed.json()["results"][0]
    assert row["title"] == "登录"
    assert "source_text" not in row
    assert "document_markdown" not in row


def test_draft_list_is_private():
    owner_client, owner = _client("owner")
    other_client, _other = _client("other")
    RequirementDraft.objects.create(title="仅自己可见", source_text=SAMPLE, created_by=owner)
    own = owner_client.get("/api/requirement-analysis/drafts/")
    other = other_client.get("/api/requirement-analysis/drafts/")
    assert own.json()["count"] == 1
    assert other.json()["count"] == 0


def test_missing_model_is_rejected():
    client, _user = _client()
    response = client.post(
        "/api/requirement-analysis/drafts/",
        {"title": "登录", "text": SAMPLE},
        format="json",
    )
    assert response.status_code == 400
    assert "模型" in response.json()["error"]


def test_model_failure_is_saved(monkeypatch):
    client, user = _client()
    _config(user)

    def fail(config, text, title):
        raise RequirementWriteError("模型没有返回需求文档")

    monkeypatch.setattr("apps.requirement_analysis.requirement_writer_views.write_requirement", fail)
    response = client.post(
        "/api/requirement-analysis/drafts/",
        {"title": "登录", "text": SAMPLE},
        format="json",
    )
    assert response.status_code == 201
    assert response.json()["status"] == "failed"
    assert "需求文档" in response.json()["error_message"]


def _completed_draft(user):
    written = _written()
    return RequirementDraft.objects.create(
        title="登录",
        source_text=SAMPLE,
        document_markdown=written["document_markdown"],
        sections=written["sections"],
        acceptance_criteria=written["acceptance_criteria"],
        open_questions=written["open_questions"],
        created_by=user,
        status=RequirementDraft.STATUS_COMPLETED,
    )


def test_patch_saves_edited_markdown():
    client, user = _client()
    draft = _completed_draft(user)
    edited = MARKDOWN + "补充：验证码只对当前手机号有效。\n"
    response = client.patch(
        f"/api/requirement-analysis/drafts/{draft.id}/",
        {"document_markdown": edited},
        format="json",
    )
    assert response.status_code == 200
    assert "当前手机号" in response.json()["document_markdown"]
    draft.refresh_from_db()
    assert "当前手机号" in draft.document_markdown


def test_failed_draft_cannot_be_saved():
    client, user = _client()
    draft = RequirementDraft.objects.create(
        title="登录",
        source_text=SAMPLE,
        created_by=user,
        status=RequirementDraft.STATUS_FAILED,
        error_message="失败",
    )
    response = client.patch(
        f"/api/requirement-analysis/drafts/{draft.id}/",
        {"document_markdown": MARKDOWN},
        format="json",
    )
    assert response.status_code == 400


def test_finalize_creates_then_updates_document():
    client, user = _client()
    draft = _completed_draft(user)
    first = client.post(f"/api/requirement-analysis/drafts/{draft.id}/finalize/")
    assert first.status_code == 200
    document_id = first.json()["document"]
    document = RequirementDocument.objects.get(pk=document_id)
    assert document.document_type == "md"
    assert document.uploaded_by == user
    assert "进入首页" in document.extracted_text
    assert document.file_size > 0

    client.patch(
        f"/api/requirement-analysis/drafts/{draft.id}/",
        {"title": "手机号登录", "document_markdown": MARKDOWN},
        format="json",
    )
    second = client.post(f"/api/requirement-analysis/drafts/{draft.id}/finalize/")
    assert second.status_code == 200
    assert second.json()["document"] == document_id
    assert RequirementDocument.objects.count() == 1
    document.refresh_from_db()
    assert document.title == "手机号登录"
    assert "进入首页" in document.extracted_text


def test_review_links_quality_review(monkeypatch):
    client, user = _client()
    _config(user, role="writer")
    draft = _completed_draft(user)

    def fake_review(config, text, title):
        assert title == "登录"
        assert "进入首页" in text
        return normalize_review({
            "completeness_score": 70,
            "consistency_score": 80,
            "testability_score": 40,
            "summary": "状态变化还没写清。",
            "findings": [],
        })

    monkeypatch.setattr("apps.requirement_analysis.requirement_writer_views.review_requirement", fake_review)
    response = client.post(f"/api/requirement-analysis/drafts/{draft.id}/review/")
    assert response.status_code == 201
    body = response.json()
    assert body["review"]["verdict"] == "revise"
    assert body["draft"]["latest_review"] == body["review"]["id"]
    assert RequirementQualityReview.objects.filter(created_by=user).count() == 1

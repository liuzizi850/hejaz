import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.requirement_analysis.models import AIModelConfig, RequirementDocument, RequirementQualityReview
from apps.requirement_analysis.quality_review import (
    QualityReviewError,
    normalize_review,
    parse_model_payload,
    prepare_text,
)
from apps.users.models import User

pytestmark = pytest.mark.django_db

SAMPLE = "用户使用手机号和验证码登录。验证码 5 分钟内有效，连续错误 3 次锁定 30 分钟。"


def _client(username="reviewer"):
    user = User.objects.create_user(username=username, password="pass123456")
    client = APIClient()
    client.force_authenticate(user)
    return client, user


def _config(user, role="reviewer"):
    return AIModelConfig.objects.create(
        name=f"{role}-{user.username}",
        model_type="other",
        role=role,
        base_url="https://example.com/v1",
        model_name="fake-review",
        created_by=user,
        is_active=True,
    )


def _report():
    return {
        "completeness_score": 90,
        "consistency_score": 88,
        "testability_score": 96,
        "summary": "完成时限没有写死。",
        "findings": [{
            "dimension": "testability",
            "issue_type": "ambiguity",
            "severity": "high",
            "location": "第2条",
            "quote": "尽快完成",
            "problem": "没有可观察的完成时限",
            "suggestion": "写明接口在 3 秒内返回结果",
        }],
    }


def test_parse_fenced_json_and_force_block():
    raw = """```json
    {"completeness_score": 95, "consistency_score": 90, "testability_score": 99,
     "summary": "有一处测不了。",
     "findings": [{"dimension": "testability", "issue_type": "ambiguity", "severity": "high",
                   "location": "第2条", "quote": "尽快完成", "problem": "没有时限", "suggestion": "写成 3 秒内"}]}
    ```"""
    report = normalize_review(parse_model_payload(raw))
    assert report["verdict"] == "block"
    assert report["testability_score"] <= 59
    assert report["completeness_score"] == 95
    assert report["findings"][0]["blocks_test"] is True
    assert report["findings"][0]["id"] == "F1"


def test_medium_finding_means_revise_and_caps_that_dimension():
    report = normalize_review({
        "completeness_score": 40,
        "consistency_score": 92,
        "testability_score": 90,
        "summary": "术语不统一。",
        "findings": [{
            "dimension": "一致性",
            "issue_type": "冲突",
            "severity": "中",
            "problem": "「锁定」和「冻结」指的不是同一件事",
            "suggestion": "统一用锁定，并写明解锁条件",
        }],
    })
    assert report["verdict"] == "revise"
    assert report["consistency_score"] <= 79
    assert report["completeness_score"] == 40


def test_low_score_without_findings_needs_revision():
    report = normalize_review({
        "completeness_score": 40,
        "consistency_score": 80,
        "testability_score": 80,
        "summary": "缺了一大块。",
        "findings": [],
    })
    assert report["verdict"] == "revise"


def test_clean_requirement_passes():
    report = normalize_review({
        "completeness_score": 86,
        "consistency_score": 90,
        "testability_score": 88,
        "summary": "可以写用例。",
        "findings": [],
    })
    assert report["verdict"] == "pass"
    assert report["overall_score"] == 88


def test_drop_finding_without_problem_and_fill_summary():
    report = normalize_review({"findings": [{"dimension": "completeness", "problem": ""}]})
    assert report["findings"] == []
    assert report["verdict"] == "pass"
    assert "用例设计" in report["summary"]


def test_unparseable_model_output():
    with pytest.raises(QualityReviewError):
        parse_model_payload("这不是审查结果")


def test_short_text_rejected():
    with pytest.raises(QualityReviewError):
        prepare_text("太短")


def test_review_requires_text():
    client, user = _client()
    _config(user)
    response = client.post("/api/requirement-analysis/quality-reviews/", {"title": "登录"}, format="json")
    assert response.status_code == 400
    assert RequirementQualityReview.objects.count() == 0


def test_review_requires_login():
    response = APIClient().post(
        "/api/requirement-analysis/quality-reviews/",
        {"title": "登录", "text": SAMPLE},
        format="json",
    )
    assert response.status_code == 401


def test_review_persists_block(monkeypatch):
    client, user = _client()
    _config(user)

    def fake_review(config, text, title):
        assert title == "登录"
        assert "验证码" in text
        return normalize_review(_report())

    monkeypatch.setattr(
        "apps.requirement_analysis.quality_review_views.review_requirement",
        fake_review,
    )
    response = client.post(
        "/api/requirement-analysis/quality-reviews/",
        {"title": "登录", "text": SAMPLE},
        format="json",
    )
    assert response.status_code == 201
    body = response.json()
    assert body["verdict"] == "block"
    assert body["model_name"] == "fake-review"
    assert body["findings"][0]["issue_type"] == "ambiguity"
    assert "source_text" in body

    listed = client.get("/api/requirement-analysis/quality-reviews/")
    row = listed.json()["results"][0]
    assert row["verdict"] == "block"
    assert "source_text" not in row


def test_review_list_is_private():
    owner_client, owner = _client("owner")
    other_client, _other = _client("other")
    RequirementQualityReview.objects.create(
        title="仅自己可见",
        source_text=SAMPLE,
        created_by=owner,
        verdict="pass",
        summary="可以通过",
    )
    own = owner_client.get("/api/requirement-analysis/quality-reviews/")
    other = other_client.get("/api/requirement-analysis/quality-reviews/")
    assert own.json()["count"] == 1
    assert other.json()["count"] == 0


def test_review_uses_document_text(monkeypatch):
    client, user = _client()
    _config(user)
    document = RequirementDocument.objects.create(
        title="登录说明",
        file=SimpleUploadedFile("login.txt", SAMPLE.encode("utf-8")),
        document_type="txt",
        uploaded_by=user,
        extracted_text=SAMPLE,
    )
    monkeypatch.setattr(
        "apps.requirement_analysis.quality_review_views.review_requirement",
        lambda config, text, title: normalize_review({
            "completeness_score": 80,
            "consistency_score": 80,
            "testability_score": 80,
            "summary": "可以写用例。",
            "findings": [],
        }),
    )
    response = client.post(
        "/api/requirement-analysis/quality-reviews/",
        {"title": "登录说明", "document": document.id},
        format="json",
    )
    assert response.status_code == 201
    assert response.json()["verdict"] == "pass"
    assert response.json()["document"] == document.id


def test_missing_model_is_rejected():
    client, _user = _client()
    response = client.post(
        "/api/requirement-analysis/quality-reviews/",
        {"title": "登录", "text": SAMPLE},
        format="json",
    )
    assert response.status_code == 400
    assert "模型" in response.json()["error"]


def test_model_failure_is_saved(monkeypatch):
    client, user = _client()
    _config(user)

    def fail(config, text, title):
        raise QualityReviewError("模型没有返回审查结果")

    monkeypatch.setattr("apps.requirement_analysis.quality_review_views.review_requirement", fail)
    response = client.post(
        "/api/requirement-analysis/quality-reviews/",
        {"title": "登录", "text": SAMPLE},
        format="json",
    )
    assert response.status_code == 201
    assert response.json()["status"] == "failed"
    assert "审查结果" in response.json()["error_message"]

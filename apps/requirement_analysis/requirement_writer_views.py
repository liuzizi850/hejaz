"""需求文档辅助撰写：整理散乱输入，保存草稿，定稿或送审。"""

import logging

from django.core.files.base import ContentFile
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.projects.models import Project
from apps.requirement_analysis.models import (
    AIModelConfig,
    RequirementDocument,
    RequirementDraft,
    RequirementQualityReview,
)
from apps.requirement_analysis.quality_review import QualityReviewError, prepare_text, review_requirement
from apps.requirement_analysis.requirement_writer import (
    RequirementWriteError,
    prepare_source,
    write_requirement,
)
from apps.requirement_analysis.serializers import (
    RequirementDraftListSerializer,
    RequirementDraftSerializer,
    RequirementQualityReviewSerializer,
)

logger = logging.getLogger(__name__)

MIN_DOCUMENT_CHARS = 20
MAX_DOCUMENT_CHARS = 30000


class RequirementDraftViewSet(viewsets.ModelViewSet):
    """整理散乱输入，生成可编辑的需求草稿。"""

    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return RequirementDraft.objects.filter(created_by=self.request.user).select_related(
            "project", "document", "latest_review"
        )

    def get_serializer_class(self):
        if self.action == "list":
            return RequirementDraftListSerializer
        return RequirementDraftSerializer

    def create(self, request, *args, **kwargs):
        title = _title(request.data.get("title"))
        if isinstance(title, Response):
            return title
        project = _project(request.data.get("project"))
        if project is False:
            return Response({"error": "项目不存在"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            text, truncated = prepare_source(request.data.get("text"))
        except RequirementWriteError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        config = _active_model()
        if config is None:
            return Response(
                {"error": "没有启用的编写模型或评审模型，请先在配置中心启用一个模型"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        draft = RequirementDraft(
            title=title,
            source_text=text,
            project=project,
            created_by=request.user,
            input_truncated=truncated,
            model_name=config.model_name or "",
        )
        try:
            written = write_requirement(config, text, title)
        except RequirementWriteError as exc:
            draft.status = RequirementDraft.STATUS_FAILED
            draft.error_message = str(exc)[:2000]
            draft.save()
            return Response(self.get_serializer(draft).data, status=status.HTTP_201_CREATED)
        except Exception:
            logger.exception("requirement draft writing failed")
            draft.status = RequirementDraft.STATUS_FAILED
            draft.error_message = "整理失败，请稍后重试"
            draft.save()
            return Response(self.get_serializer(draft).data, status=status.HTTP_201_CREATED)

        markdown = written["document_markdown"]
        if truncated:
            markdown = "原文超过 30000 字，本次只整理了前 30000 字。\n\n" + markdown
        draft.status = RequirementDraft.STATUS_COMPLETED
        draft.sections = written["sections"]
        draft.acceptance_criteria = written["acceptance_criteria"]
        draft.open_questions = written["open_questions"]
        draft.document_markdown = markdown
        draft.save()
        return Response(self.get_serializer(draft).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        draft = get_object_or_404(self.get_queryset(), pk=kwargs.get("pk"))
        if draft.status != RequirementDraft.STATUS_COMPLETED:
            return Response({"error": "整理失败的草稿不能保存"}, status=status.HTTP_400_BAD_REQUEST)
        changed = False
        if "title" in request.data:
            title = _title(request.data.get("title"))
            if isinstance(title, Response):
                return title
            draft.title = title
            changed = True
        if "document_markdown" in request.data:
            markdown = _markdown(request.data.get("document_markdown"))
            if isinstance(markdown, Response):
                return markdown
            draft.document_markdown = markdown
            changed = True
        if not changed:
            return Response({"error": "请提供要保存的标题或正文"}, status=status.HTTP_400_BAD_REQUEST)
        draft.save()
        return Response(self.get_serializer(draft).data)

    def destroy(self, request, *args, **kwargs):
        draft = get_object_or_404(self.get_queryset(), pk=kwargs.get("pk"))
        draft.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def finalize(self, request, pk=None):
        draft = self._editable(pk)
        if isinstance(draft, Response):
            return draft
        document = _save_document(draft, request.user)
        draft.document = document
        draft.save(update_fields=["document", "updated_at"])
        return Response(self.get_serializer(draft).data)

    @action(detail=True, methods=["post"])
    def review(self, request, pk=None):
        draft = self._editable(pk)
        if isinstance(draft, Response):
            return draft
        try:
            text, truncated = prepare_text(draft.document_markdown)
        except QualityReviewError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        config = _review_model()
        if config is None:
            return Response(
                {"error": "没有启用的评审模型或编写模型，请先在配置中心启用一个模型"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        review = RequirementQualityReview(
            title=draft.title,
            source_text=text,
            document=draft.document,
            project=draft.project,
            created_by=request.user,
            input_truncated=truncated or draft.input_truncated,
            model_name=config.model_name or "",
        )
        try:
            report = review_requirement(config, text, draft.title)
        except QualityReviewError as exc:
            review.status = RequirementQualityReview.STATUS_FAILED
            review.error_message = str(exc)[:2000]
            review.save()
            draft.latest_review = review
            draft.save(update_fields=["latest_review", "updated_at"])
            return Response(_review_payload(draft, review), status=status.HTTP_201_CREATED)
        except Exception:
            logger.exception("requirement draft review failed")
            review.status = RequirementQualityReview.STATUS_FAILED
            review.error_message = "审查失败，请稍后重试"
            review.save()
            draft.latest_review = review
            draft.save(update_fields=["latest_review", "updated_at"])
            return Response(_review_payload(draft, review), status=status.HTTP_201_CREATED)

        if truncated:
            report["summary"] = "正文超过 30000 字，本次只审查了前 30000 字。\n" + report["summary"]
        review.status = RequirementQualityReview.STATUS_COMPLETED
        review.verdict = report["verdict"]
        review.completeness_score = report["completeness_score"]
        review.consistency_score = report["consistency_score"]
        review.testability_score = report["testability_score"]
        review.overall_score = report["overall_score"]
        review.summary = report["summary"]
        review.findings = report["findings"]
        review.save()
        draft.latest_review = review
        draft.save(update_fields=["latest_review", "updated_at"])
        return Response(_review_payload(draft, review), status=status.HTTP_201_CREATED)

    def _editable(self, pk):
        draft = get_object_or_404(self.get_queryset(), pk=pk)
        if draft.status != RequirementDraft.STATUS_COMPLETED:
            return Response({"error": "这份草稿还没有整理成功"}, status=status.HTTP_400_BAD_REQUEST)
        markdown = _markdown(draft.document_markdown)
        if isinstance(markdown, Response):
            return markdown
        return draft


def _title(value):
    title = str(value or "").strip()
    if not title:
        return Response({"error": "请填写需求标题"}, status=status.HTTP_400_BAD_REQUEST)
    if len(title) > 200:
        return Response({"error": "标题不能超过 200 字"}, status=status.HTTP_400_BAD_REQUEST)
    return title


def _markdown(value):
    text = str(value or "").strip()
    if len(text) < MIN_DOCUMENT_CHARS:
        return Response({"error": "需求正文过短，至少需要 20 个字"}, status=status.HTTP_400_BAD_REQUEST)
    if len(text) > MAX_DOCUMENT_CHARS:
        return Response({"error": "需求正文不能超过 30000 字"}, status=status.HTTP_400_BAD_REQUEST)
    return text + "\n"


def _project(value):
    if value in (None, "", "null"):
        return None
    try:
        project = Project.objects.filter(pk=value).first()
    except (TypeError, ValueError):
        return False
    if project is None:
        return False
    return project


def _active_model():
    config = AIModelConfig.objects.filter(role="writer", is_active=True).order_by("-updated_at").first()
    if config:
        return config
    return AIModelConfig.objects.filter(role="reviewer", is_active=True).order_by("-updated_at").first()


def _review_model():
    config = AIModelConfig.objects.filter(role="reviewer", is_active=True).order_by("-updated_at").first()
    if config:
        return config
    return AIModelConfig.objects.filter(role="writer", is_active=True).order_by("-updated_at").first()


def _save_document(draft: RequirementDraft, user) -> RequirementDocument:
    payload = draft.document_markdown.encode("utf-8")
    if draft.document_id:
        document = draft.document
    else:
        document = RequirementDocument(
            title=draft.title,
            document_type="md",
            status="uploaded",
            uploaded_by=user,
            project=draft.project,
        )
    document.title = draft.title
    document.project = draft.project
    document.document_type = "md"
    document.extracted_text = draft.document_markdown
    document.file_size = len(payload)
    document.file.save(f"draft-{draft.id}.md", ContentFile(payload), save=False)
    document.save()
    return document


def _review_payload(draft, review):
    return {
        "draft": RequirementDraftSerializer(draft).data,
        "review": RequirementQualityReviewSerializer(review).data,
    }

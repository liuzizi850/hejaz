import logging
import os
import tempfile
from pathlib import Path

from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.response import Response

from apps.projects.models import Project
from apps.requirement_analysis.models import AIModelConfig, RequirementDocument, RequirementQualityReview
from apps.requirement_analysis.quality_review import (
    QualityReviewError,
    prepare_text,
    review_requirement,
)
from apps.requirement_analysis.serializers import (
    RequirementQualityReviewListSerializer,
    RequirementQualityReviewSerializer,
)
from apps.requirement_analysis.services import DocumentProcessor

logger = logging.getLogger(__name__)

_EXTRACTORS = {
    ".pdf": DocumentProcessor.extract_text_from_pdf,
    ".docx": DocumentProcessor.extract_text_from_docx,
    ".txt": DocumentProcessor.extract_text_from_txt,
    ".md": DocumentProcessor.extract_text_from_txt,
}
_EXTRACT_FAILURES = (
    "PDF文本提取失败",
    "Word文档文本提取失败",
    "文本文件读取失败",
    "不支持的文档类型",
)


class RequirementQualityReviewViewSet(viewsets.ModelViewSet):
    """审查需求正文，返回完整性、一致性、可测性结论。"""

    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        queryset = RequirementQualityReview.objects.filter(
            created_by=self.request.user
        ).select_related("project", "document")
        verdict = self.request.query_params.get("verdict")
        if verdict:
            queryset = queryset.filter(verdict=verdict)
        return queryset

    def get_serializer_class(self):
        if self.action == "list":
            return RequirementQualityReviewListSerializer
        return RequirementQualityReviewSerializer

    def create(self, request, *args, **kwargs):
        title = str(request.data.get("title") or "").strip()
        if not title:
            return Response({"error": "请填写需求标题"}, status=status.HTTP_400_BAD_REQUEST)
        if len(title) > 200:
            return Response({"error": "标题不能超过 200 字"}, status=status.HTTP_400_BAD_REQUEST)

        project = _project(request.data.get("project"))
        if project is False:
            return Response({"error": "项目不存在"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            text, document = _source_text(request)
            text, truncated = prepare_text(text)
        except QualityReviewError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        config = _active_model()
        if config is None:
            return Response(
                {"error": "没有启用的评审模型或编写模型，请先在配置中心启用一个模型"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        review = RequirementQualityReview(
            title=title,
            source_text=text,
            document=document,
            project=project,
            created_by=request.user,
            input_truncated=truncated,
            model_name=config.model_name or "",
        )
        try:
            report = review_requirement(config, text, title)
        except QualityReviewError as exc:
            review.status = RequirementQualityReview.STATUS_FAILED
            review.error_message = str(exc)[:2000]
            review.save()
            serializer = self.get_serializer(review)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except Exception:
            logger.exception("requirement quality review failed")
            review.status = RequirementQualityReview.STATUS_FAILED
            review.error_message = "审查失败，请稍后重试"
            review.save()
            serializer = self.get_serializer(review)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

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
        serializer = self.get_serializer(review)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        review = get_object_or_404(self.get_queryset(), pk=kwargs.get("pk"))
        review.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


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


def _source_text(request):
    text = str(request.data.get("text") or "").strip()
    if text:
        return text, _document(request.data.get("document"))
    upload = request.FILES.get("file")
    if upload:
        return _text_from_upload(upload), None
    document = _document(request.data.get("document"))
    if document is None:
        raise QualityReviewError("请粘贴需求正文，或上传 txt、md、docx、pdf")
    extracted = document.extracted_text or ""
    if not extracted.strip():
        extracted = DocumentProcessor.extract_text(document)
        if extracted and not extracted.startswith(_EXTRACT_FAILURES):
            document.extracted_text = extracted
            document.save(update_fields=["extracted_text", "updated_at"])
    return extracted, document


def _document(value):
    if value in (None, "", "null"):
        return None
    try:
        document = RequirementDocument.objects.filter(pk=value).first()
    except (TypeError, ValueError):
        document = None
    if document is None:
        raise QualityReviewError("需求文档不存在")
    return document


def _text_from_upload(uploaded) -> str:
    suffix = Path(uploaded.name or "").suffix.lower()
    extractor = _EXTRACTORS.get(suffix)
    if extractor is None:
        raise QualityReviewError("只支持 txt、md、docx、pdf")
    fd, path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as handle:
            for chunk in uploaded.chunks():
                handle.write(chunk)
        return extractor(path)
    finally:
        os.unlink(path)


def _active_model():
    config = AIModelConfig.objects.filter(role="reviewer", is_active=True).order_by("-updated_at").first()
    if config:
        return config
    return AIModelConfig.objects.filter(role="writer", is_active=True).order_by("-updated_at").first()

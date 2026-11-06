from django.core.cache import caches
from django.http import FileResponse
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.code_monitor.acquire import AcquireError, ensure_http_git_url
from apps.code_monitor.models import CodeAddress, ScanTask
from apps.code_monitor.serializers import CodeAddressSerializer, ScanTaskSerializer
from apps.code_monitor.tasks import run_code_monitor_scan, token_cache_key
from apps.requirement_analysis.models import AIModelConfig


class CodeMonitorPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 200


class CodeAddressViewSet(viewsets.ModelViewSet):
    serializer_class = CodeAddressSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = CodeMonitorPagination
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        return CodeAddress.objects.filter(created_by=self.request.user)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class ScanTaskViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = ScanTaskSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = CodeMonitorPagination
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        return ScanTask.objects.filter(created_by=self.request.user).select_related("model_config")

    def create(self, request, *args, **kwargs):
        address_id = request.data.get("address_id")
        archive = request.FILES.get("archive")
        if bool(address_id) == bool(archive):
            raise ValidationError("请选择一个代码地址，或上传一个 zip")
        config = AIModelConfig.objects.filter(id=request.data.get("model_config_id"), is_active=True).first()
        if config is None:
            raise ValidationError("没有已启用的模型配置")
        if address_id:
            address = self._own_address(address_id)
            task = ScanTask.objects.create(
                source_type=ScanTask.SOURCE_GIT,
                git_url=self._git_url(address.git_url),
                model_config=config,
                created_by=request.user,
            )
        else:
            if not archive.name.lower().endswith(".zip"):
                raise ValidationError("取代码失败: zip 打不开")
            task = ScanTask.objects.create(
                source_type=ScanTask.SOURCE_ZIP,
                archive=archive,
                model_config=config,
                created_by=request.user,
            )
        token = str(request.data.get("token") or "")
        token_cache = caches["code_monitor"]
        if token:
            token_cache.set(token_cache_key(task.id), token, timeout=700)
        try:
            run_code_monitor_scan.delay(task.id)
        except Exception:
            token_cache.delete(token_cache_key(task.id))
            task.status = ScanTask.STATUS_FAILED
            task.error_message = "提交扫描失败"
            try:
                if task.archive:
                    task.archive.delete(save=False)
            except Exception:
                pass
            task.save(update_fields=["status", "error_message", "archive", "updated_at"])
            return Response({"detail": "提交扫描失败"}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ScanTaskSerializer(task).data, status=status.HTTP_201_CREATED)

    def _git_url(self, url):
        try:
            return ensure_http_git_url(url)
        except AcquireError as exc:
            raise ValidationError(str(exc)) from exc

    def _own_address(self, address_id):
        address = CodeAddress.objects.filter(id=address_id, created_by=self.request.user).first()
        if address is None:
            raise ValidationError("代码地址不存在")
        return address

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        task = self.get_object()
        if task.status != ScanTask.STATUS_SUCCEEDED or not task.result_file:
            return Response({"detail": "结果文件不存在"}, status=status.HTTP_404_NOT_FOUND)
        return FileResponse(
            task.result_file.open("rb"),
            as_attachment=True,
            filename=f"api-extract-{task.id}.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

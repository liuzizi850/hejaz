# -*- coding: utf-8 -*-
"""APP测试执行管理视图"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.filters import SearchFilter
from django.db.models import Q
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone
from django.http import FileResponse, Http404
import logging
import os

from ..models import AppTestExecution
from ..serializers import AppTestExecutionSerializer
from ..tasks import send_execution_update
from .test_case_views import AppPagination

logger = logging.getLogger(__name__)


class AppTestExecutionViewSet(viewsets.ModelViewSet):
    """APP测试执行记录 ViewSet"""
    queryset = AppTestExecution.objects.all()
    serializer_class = AppTestExecutionSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ['status', 'test_case', 'device']
    search_fields = ['test_case__name', 'device__name', 'device__device_id', 'user__username']
    pagination_class = AppPagination
    
    def get_queryset(self):
        queryset = super().get_queryset()

        # 支持 test_suite__isnull 过滤，用于区分单独执行和套件执行
        suite_isnull = self.request.query_params.get('test_suite__isnull')
        if suite_isnull is not None:
            queryset = queryset.filter(test_suite__isnull=(suite_isnull.lower() in ('true', '1')))

        # 支持按项目间接过滤（通过 test_case.project）
        project_id = self.request.query_params.get('project')
        if project_id:
            queryset = queryset.filter(test_case__project_id=project_id)

        search_value = (self.request.query_params.get('search') or '').strip()
        if not search_value:
            return queryset
        return queryset.filter(
            Q(test_case__name__icontains=search_value) |
            Q(device__name__icontains=search_value) |
            Q(device__device_id__icontains=search_value) |
            Q(user__username__icontains=search_value)
        )
    
    @action(detail=False, methods=['get'])
    def ws_status(self, request):
        """检查 WebSocket 是否可用"""
        try:
            import daphne
            from channels.layers import get_channel_layer
            channel_layer = get_channel_layer()
            ws_available = channel_layer is not None and not isinstance(
                channel_layer, type(None)
            )
            # 检查是否通过 ASGI 服务器运行（非 runserver）
            server_type = request.META.get('SERVER_SOFTWARE', '')
            is_asgi = 'daphne' in server_type.lower() or request.META.get('asgi', False)
            return Response({'websocket': ws_available and is_asgi})
        except (ImportError, Exception):
            return Response({'websocket': False})

    @action(detail=True, methods=['post'])
    def stop(self, request, pk=None):
        """停止执行"""
        execution = self.get_object()
        
        if execution.status not in ['pending', 'running']:
            return Response({
                'success': False,
                'message': '只能停止待执行或执行中的任务'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            # 停止 Celery 任务
            if execution.task_id:
                from celery import current_app
                current_app.control.revoke(execution.task_id, terminate=True, signal='SIGTERM')
                logger.info(f"Celery任务已终止: task_id={execution.task_id}")
            
            execution.status = 'stopped'
            execution.finished_at = timezone.now()
            if execution.started_at:
                execution.duration = (execution.finished_at - execution.started_at).total_seconds()
            execution.save()
            send_execution_update(
                execution.id,
                status='stopped',
                progress=execution.progress,
                message='任务已停止',
                report_path=execution.report_path,
                finished_at=execution.finished_at
            )
            
            return Response({
                'success': True,
                'message': '任务已停止'
            })
        except Exception as e:
            logger.error(f"停止任务失败: {str(e)}")
            return Response({
                'success': False,
                'message': f'停止任务失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=["get"], url_path="bundle-report")
    def bundle_report(self, request, pk=None):
        execution = self.get_object()
        directory = os.path.dirname(execution.result_bundle_path or "")
        docx_path = os.path.join(directory, "report.docx") if directory else ""
        if not os.path.isfile(docx_path):
            return Response({"message": "报告不存在"}, status=status.HTTP_404_NOT_FOUND)
        from ..recording.adb_gateway import to_media_url
        from ..recording.report_pack import playable_video, read_report_steps

        steps = []
        for row in read_report_steps(docx_path):
            shot_name = row.get("screenshot") or ""
            shot_path = os.path.join(directory, shot_name) if shot_name else ""
            row["screenshot_url"] = to_media_url(shot_path) if shot_path and os.path.isfile(shot_path) else ""
            steps.append(row)
        video_url = to_media_url(playable_video(directory))
        return Response({
            "steps": steps,
            "download_url": to_media_url(execution.result_bundle_path),
            "video_url": video_url,
        })

    def _selected_executions(self, request):
        raw = request.data.get("ids") if isinstance(request.data, dict) else None
        if not isinstance(raw, list) or not raw:
            return None, Response({"message": "请选择执行记录"}, status=status.HTTP_400_BAD_REQUEST)
        ids = []
        for item in raw:
            try:
                ids.append(int(item))
            except (TypeError, ValueError):
                continue
        ids = list(dict.fromkeys(ids))[:30]
        if not ids:
            return None, Response({"message": "请选择执行记录"}, status=status.HTTP_400_BAD_REQUEST)
        found = {item.id: item for item in self.get_queryset().filter(id__in=ids)}
        ordered = [found[item] for item in ids if item in found]
        if not ordered:
            return None, Response({"message": "执行记录不存在"}, status=status.HTTP_404_NOT_FOUND)
        return ordered, None

    def _delete_blocked(self, executions):
        if any(item.status in ("pending", "running") for item in executions):
            return Response({"message": "执行中的记录不能删除"}, status=status.HTTP_400_BAD_REQUEST)
        return None

    def _remove_execution_files(self, execution):
        import shutil
        from django.conf import settings

        root = os.path.abspath(settings.MEDIA_ROOT)
        targets = [os.path.join(root, "app-automation", "results", str(execution.id))]
        report = os.path.abspath(execution.report_path) if execution.report_path else ""
        if report.startswith(root + os.sep):
            targets.append(report)
        for path in targets:
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)

    def destroy(self, request, *args, **kwargs):
        execution = self.get_object()
        blocked = self._delete_blocked([execution])
        if blocked is not None:
            return blocked
        self._remove_execution_files(execution)
        execution.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["post"], url_path="batch-delete")
    def batch_delete(self, request):
        executions, error = self._selected_executions(request)
        if error is not None:
            return error
        blocked = self._delete_blocked(executions)
        if blocked is not None:
            return blocked
        for execution in executions:
            self._remove_execution_files(execution)
        deleted = AppTestExecution.objects.filter(id__in=[item.id for item in executions]).delete()[0]
        return Response({"deleted": deleted})

    def _report_records(self, executions):
        from ..recording.report_pack import read_report_steps

        step_text = {"passed": "通过", "failed": "失败"}
        result_text = {"passed": "通过", "failed": "失败", "skipped": "跳过"}
        records = []
        for execution in executions:
            case_name = execution.test_case.name if execution.test_case_id and execution.test_case else ""
            directory = os.path.dirname(execution.result_bundle_path or "")
            docx_path = os.path.join(directory, "report.docx") if directory else ""
            steps = []
            if os.path.isfile(docx_path):
                for row in read_report_steps(docx_path):
                    shot_name = row.get("screenshot") or ""
                    shot_path = os.path.join(directory, shot_name) if shot_name else ""
                    steps.append({
                        "order": row.get("order") or "",
                        "name": row.get("name") or "",
                        "status": step_text.get(row.get("status") or "", row.get("status") or ""),
                        "reason": row.get("reason") or "",
                        "image_path": shot_path if shot_path and os.path.isfile(shot_path) else "",
                    })
            records.append({
                "id": execution.id,
                "case_name": case_name,
                "result": result_text.get(execution.result or "", execution.result or ""),
                "error": execution.error_message or "",
                "steps": steps,
            })
        return records

    def _file_response(self, path, filename, content_type):
        response = FileResponse(open(path, "rb"), as_attachment=True, filename=filename, content_type=content_type)
        response._cleanup_path = path
        original_close = response.close

        def close():
            original_close()
            try:
                os.remove(path)
            except OSError:
                pass

        response.close = close
        return response

    @action(detail=False, methods=["post"], url_path="batch-download")
    def batch_download(self, request):
        import tempfile
        from ..recording.report_export import pack_report_files, safe_download_name

        executions, error = self._selected_executions(request)
        if error is not None:
            return error
        files = []
        notes = []
        for execution in executions:
            case_name = execution.test_case.name if execution.test_case_id and execution.test_case else "报告"
            base = "%s-%s" % (execution.id, safe_download_name(case_name))
            bundle = execution.result_bundle_path or ""
            if os.path.isfile(bundle):
                files.append((base + ".zip", bundle))
            else:
                notes.append((base + ".txt", execution.error_message or "这份执行没有报告文件"))
        fd, destination = tempfile.mkstemp(suffix=".zip")
        os.close(fd)
        pack_report_files(destination, files, notes)
        return self._file_response(destination, "执行报告.zip", "application/zip")

    @action(detail=False, methods=["post"], url_path="batch-export")
    def batch_export(self, request):
        import tempfile
        from ..recording.report_export import export_executions_xlsx

        executions, error = self._selected_executions(request)
        if error is not None:
            return error
        fd, destination = tempfile.mkstemp(suffix=".xlsx")
        os.close(fd)
        export_executions_xlsx(destination, self._report_records(executions))
        return self._file_response(
            destination,
            "执行报告.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


def serve_report_file(request, execution_id, file_path=''):
    """提供 Allure 报告文件访问"""
    try:
        execution = AppTestExecution.objects.get(id=execution_id)
        if not execution.report_path:
            raise Http404("报告路径不存在")

        if not file_path:
            file_path = 'index.html'

        report_dir = execution.report_path
        full_path = os.path.join(report_dir, file_path)

        report_dir_abs = os.path.abspath(report_dir)
        full_path_abs = os.path.abspath(full_path)
        if not full_path_abs.startswith(report_dir_abs):
            raise Http404("无效的文件路径")

        if not os.path.exists(full_path_abs) or not os.path.isfile(full_path_abs):
            raise Http404("文件不存在")

        return FileResponse(open(full_path_abs, 'rb'), content_type=_get_content_type(file_path))
    except AppTestExecution.DoesNotExist:
        raise Http404("执行记录不存在")


def _get_content_type(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    content_types = {
        '.html': 'text/html',
        '.js': 'application/javascript',
        '.css': 'text/css',
        '.json': 'application/json',
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.gif': 'image/gif',
        '.svg': 'image/svg+xml',
        '.ico': 'image/x-icon',
        '.woff': 'font/woff',
        '.woff2': 'font/woff2',
        '.ttf': 'font/ttf',
        '.eot': 'application/vnd.ms-fontobject',
        '.txt': 'text/plain',
    }
    return content_types.get(ext, 'application/octet-stream')

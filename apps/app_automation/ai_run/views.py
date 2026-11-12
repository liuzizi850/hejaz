# -*- coding: utf-8 -*-
"""REQ-002 execution-and-report APIs. Share report viewing is AllowAny; everything else is login-required."""
from __future__ import annotations

import logging

from django.http import Http404
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .constants import (
    DEVICE_OFFLINE,
    INVALID_FEATURE,
    INVALID_SHARE,
    INVALID_UPLOAD,
    NO_SCRIPTS_SELECTED,
    REPORT_NOT_READY,
    RUN_NOT_FOUND,
    WORKER_NOT_READY,
)
from .devices import list_connected_android_devices
from .execution import WorkerNotReady, create_run, dispatch_run
from .models import AiRunExecution, AiRunShare
from .reports import (
    create_share,
    file_response,
    get_share,
    http_error,
    report_html_url,
    resolve_report_asset,
    share_url_path,
    zip_response,
)
from .scripts import list_available_scripts, save_uploaded_feature
from .serializers import AiRunExecutionSerializer, CreateAiRunSerializer, ShareSerializer
from .sanitize import sanitize_text

logger = logging.getLogger(__name__)


def _error(message: str, http_status=status.HTTP_400_BAD_REQUEST) -> Response:
    return Response({"success": False, "message": sanitize_text(message, fallback=message)}, status=http_status)


class AiRunScriptListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        scripts = list_available_scripts(request.user)
        return Response({"success": True, "scripts": scripts})


class AiRunScriptUploadView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        upload = request.FILES.get("file") or request.FILES.get("feature")
        if upload is None:
            return _error(INVALID_UPLOAD)
        name = getattr(upload, "name", "") or "upload.feature"
        if not str(name).lower().endswith(".feature"):
            return _error(INVALID_UPLOAD)
        try:
            raw = upload.read()
            content = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
        except UnicodeDecodeError:
            return _error(INVALID_UPLOAD)
        try:
            script = save_uploaded_feature(request.user, name, content)
        except ValueError as exc:
            return _error(str(exc) or INVALID_FEATURE)
        return Response(
            {
                "success": True,
                "script": {
                    "id": f"upload:{script.id}",
                    "name": script.display_name or script.original_name,
                    "source": "upload",
                    "original_name": script.original_name,
                },
            },
            status=status.HTTP_201_CREATED,
        )


class AiRunDeviceListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        payload = list_connected_android_devices()
        return Response({"success": True, **payload})


class AiRunListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = AiRunExecution.objects.filter(user=request.user).order_by("-created_at")[:50]
        return Response({"success": True, "runs": AiRunExecutionSerializer(qs, many=True).data})

    def post(self, request):
        serializer = CreateAiRunSerializer(data=request.data)
        if not serializer.is_valid():
            return _error(NO_SCRIPTS_SELECTED if "script_ids" in serializer.errors else DEVICE_OFFLINE)
        try:
            run = create_run(
                request.user,
                serializer.validated_data["serial"],
                serializer.validated_data["script_ids"],
            )
            dispatch_run(run)
            run.refresh_from_db()
        except WorkerNotReady as exc:
            return _error(str(exc) or WORKER_NOT_READY, http_status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except ValueError as exc:
            return _error(str(exc))
        except Exception:
            logger.exception("REQ-002 failed to create or dispatch a run")
            return _error(WORKER_NOT_READY, http_status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(
            {"success": True, "run": AiRunExecutionSerializer(run).data},
            status=status.HTTP_201_CREATED,
        )


class AiRunDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, run_id):
        run = _owned_run(request.user, run_id)
        data = AiRunExecutionSerializer(run).data
        if run.view_token:
            data["report_html_url"] = report_html_url(run)
        return Response({"success": True, "run": data})


class AiRunReportView(APIView):
    """Host index.html and screenshots for one run.

    Authenticated owners may access directly. The in-page viewer and the
    public share link use unguessable tokens; directories are not listable.
    """

    permission_classes = [AllowAny]
    authentication_classes = []  # token or DRF session is applied manually to avoid login redirects

    def get(self, request, run_id, view_token=None, file_path=""):
        run, relpath = _run_for_report_access(request, run_id, view_token=view_token, file_path=file_path)
        try:
            asset = resolve_report_asset(run, relpath)
            return file_response(asset)
        except Exception as exc:
            return http_error(exc)


class AiRunDownloadView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, run_id):
        run = _owned_run(request.user, run_id)
        try:
            return zip_response(run)
        except Exception as exc:
            if isinstance(exc, FileNotFoundError):
                return _error(str(exc) or REPORT_NOT_READY, http_status=status.HTTP_404_NOT_FOUND)
            raise


class AiRunShareCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, run_id):
        run = _owned_run(request.user, run_id)
        try:
            share = create_share(run, request.user)
        except FileNotFoundError as exc:
            return _error(str(exc) or REPORT_NOT_READY, http_status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {"success": True, "share": ShareSerializer({"token": share.token}).data},
            status=status.HTTP_201_CREATED,
        )


class AiRunShareReportView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, token, file_path=""):
        try:
            share = get_share(token)
        except AiRunShare.DoesNotExist:
            raise Http404(INVALID_SHARE)
        run = share.execution
        if run.status != AiRunExecution.STATUS_COMPLETED:
            raise Http404(INVALID_SHARE)
        try:
            asset = resolve_report_asset(run, file_path)
            return file_response(asset)
        except Exception as exc:
            return http_error(exc)


def _owned_run(user, run_id) -> AiRunExecution:
    try:
        return AiRunExecution.objects.get(id=run_id, user=user)
    except (AiRunExecution.DoesNotExist, ValueError, TypeError):
        raise Http404(RUN_NOT_FOUND)


def _run_for_report_access(request, run_id, view_token=None, file_path=""):
    """Return (run, relative_asset_path). Path tokens authorize relative screenshot fetches."""
    try:
        run = AiRunExecution.objects.get(id=run_id)
    except (AiRunExecution.DoesNotExist, ValueError, TypeError):
        raise Http404(RUN_NOT_FOUND)
    token = (view_token or "").strip()
    if token and token == run.view_token:
        return run, file_path or ""
    if _is_report_owner(request, run):
        # JWT owners may still hit /report/<file> without a path token.
        rel = "/".join(part for part in (token, file_path) if part) if token else (file_path or "")
        return run, rel
    raise Http404(RUN_NOT_FOUND)


def _is_report_owner(request, run) -> bool:
    from rest_framework.authentication import SessionAuthentication, TokenAuthentication
    from rest_framework_simplejwt.authentication import JWTAuthentication

    for cls in (JWTAuthentication, TokenAuthentication, SessionAuthentication):
        try:
            result = cls().authenticate(request)
        except Exception:
            result = None
        if result and result[0] and result[0].is_authenticated and run.user_id == result[0].id:
            return True
    return False

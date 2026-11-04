# -*- coding: utf-8 -*-
from django.conf import settings
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from ..models import AppDevice, AppRecordingSession, AppTestCase
from ..recording.adb_gateway import apply_reverse, parse_ui_dump, service_enabled
from ..recording.ingest import parse_ingested_event


class AppRecordingSessionViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def create(self, request):
        device_id = request.data.get("device_id")
        try:
            device = AppDevice.objects.get(device_id=device_id)
        except AppDevice.DoesNotExist:
            return Response({"message": "设备不存在"}, status=status.HTTP_404_NOT_FOUND)
        if device.status == "locked":
            return Response({"message": "设备已被锁定"}, status=status.HTTP_400_BAD_REQUEST)
        if not getattr(settings, "APP_RECORDER_SERVICE_ENABLED", False):
            return Response({"message": "请在系统设置中打开 TestHub 录制服务"}, status=status.HTTP_400_BAD_REQUEST)
        if not service_enabled(device.device_id):
            return Response({"message": "请在系统设置中打开 TestHub 录制服务"}, status=status.HTTP_400_BAD_REQUEST)
        if not apply_reverse(device.device_id):
            return Response({"message": "adb reverse 失败"}, status=status.HTTP_400_BAD_REQUEST)
        from ..recording.adb_gateway import capture_start_screen
        start_path = capture_start_screen(device.device_id)
        device.lock(request.user)
        session = AppRecordingSession.objects.create(
            device=device, user=request.user, status="recording", start_screen=start_path
        )
        return Response({"id": session.id, "status": session.status}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def interrupt(self, request, pk=None):
        session = AppRecordingSession.objects.get(pk=pk, user=request.user)
        session.status = "interrupted"
        session.save(update_fields=["status", "updated_at"])
        if session.device.locked_by_id == request.user.id:
            session.device.unlock()
        return Response({"id": session.id, "steps": session.steps})

    @action(detail=True, methods=["get"], url_path="screen-tree")
    def screen_tree(self, request, pk=None):
        from ..recording.adb_gateway import read_ui_dump
        session = AppRecordingSession.objects.get(pk=pk, user=request.user)
        xml = read_ui_dump(session.device.device_id)
        width = int((session.screen or {}).get("width") or 1080)
        height = int((session.screen or {}).get("height") or 1920)
        if not xml:
            return Response({"message": "抓不到当前界面"}, status=status.HTTP_400_BAD_REQUEST)
        return Response(parse_ui_dump(xml, width, height))

    @action(detail=True, methods=["post"], permission_classes=[AllowAny], authentication_classes=[])
    def events(self, request, pk=None):
        try:
            session = AppRecordingSession.objects.get(pk=pk)
        except AppRecordingSession.DoesNotExist:
            return Response({"message": "会话不存在"}, status=status.HTTP_404_NOT_FOUND)
        if session.status != "recording":
            return Response({"message": "会话不在录制中"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            step = parse_ingested_event(
                request.data, order=len(session.steps) + 1, template=request.data.get("template") or ""
            )
        except ValueError:
            return Response({"message": "未知事件类型"}, status=status.HTTP_400_BAD_REQUEST)
        session.steps = list(session.steps) + [step]
        if step.get("screen"):
            session.screen = step["screen"]
        session.save(update_fields=["steps", "screen", "updated_at"])
        return Response(step, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def assertions(self, request, pk=None):
        session = AppRecordingSession.objects.get(pk=pk, user=request.user)
        texts = request.data.get("expected_texts") or []
        selectors = request.data.get("expected_selectors") or []
        if not texts and not selectors:
            return Response({"message": "请勾选要校验的文字或控件"}, status=status.HTTP_400_BAD_REQUEST)
        step = {
            "type": "assert",
            "platform": "android",
            "accessibility_id": "",
            "order": len(session.steps) + 1,
            "name": "断言",
            "expected_texts": texts,
            "expected_selectors": selectors,
            "template": request.data.get("template") or "",
            "screen": session.screen,
        }
        session.steps = list(session.steps) + [step]
        session.save(update_fields=["steps", "updated_at"])
        return Response(step, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def stop(self, request, pk=None):
        session = AppRecordingSession.objects.get(pk=pk, user=request.user)
        session.status = "stopped"
        session.save(update_fields=["status", "updated_at"])
        if session.device.locked_by_id == request.user.id:
            session.device.unlock()
        return Response({"id": session.id, "steps": session.steps})

    @action(detail=True, methods=["post"])
    def save(self, request, pk=None):
        session = AppRecordingSession.objects.get(pk=pk, user=request.user)
        steps = request.data.get("steps", session.steps)
        case = AppTestCase.objects.create(
            name=request.data.get("name") or "未命名录制",
            event_chain={"platform": "android", "screen": session.screen, "steps": steps},
            start_screen=session.start_screen,
            ui_flow={},
            created_by=request.user,
        )
        empty_inputs = [step for step in steps if step.get("type") == "input" and step.get("password") and not step.get("input_text")]
        return Response({"id": case.id, "empty_password_steps": [step.get("order") for step in empty_inputs]}, status=status.HTTP_201_CREATED)

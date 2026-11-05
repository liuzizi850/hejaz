# -*- coding: utf-8 -*-
from django.conf import settings
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from ..models import AppDevice, AppRecordingSession, AppTestCase
from ..recording.adb_gateway import (
    apply_reverse,
    bounds_complete,
    broadcast_start,
    broadcast_stop,
    capture_start_screen,
    copy_case_start_screen,
    parse_ui_dump,
    save_step_image,
    service_enabled,
)
from ..recording.ingest import parse_ingested_event


def _template_for_step(device_id, session_id, order, bounds=None):
    try:
        return save_step_image(device_id, session_id, order, bounds=bounds)
    except Exception:
        return ""


def _collapsible_input(steps, payload):
    if (payload or {}).get("event_type") != "input" or not steps:
        return False
    previous = steps[-1]
    return previous.get("type") == "input" and (previous.get("resource_id") or "") == (payload.get("resource_id") or "")


def _merge_input(previous, step):
    merged = dict(previous)
    merged["input_text"] = step.get("input_text") or ""
    merged["order"] = previous.get("order")
    if not step.get("password"):
        merged["text"] = step.get("text") or ""
        merged["name"] = step.get("name") or merged.get("name") or ""
    if step.get("template"):
        merged["template"] = step["template"]
    if step.get("bounds"):
        merged["bounds"] = step["bounds"]
    if step.get("screen"):
        merged["screen"] = step["screen"]
    return merged


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
        if getattr(settings, "APP_RECORDER_SERVICE_ENABLED", None) is False:
            return Response({"message": "请在系统设置中打开 TestHub 录制服务"}, status=status.HTTP_400_BAD_REQUEST)
        if not service_enabled(device.device_id):
            return Response({"message": "请在系统设置中打开 TestHub 录制服务"}, status=status.HTTP_400_BAD_REQUEST)
        if not apply_reverse(device.device_id):
            return Response({"message": "adb reverse 失败"}, status=status.HTTP_400_BAD_REQUEST)
        device.lock(request.user)
        session = AppRecordingSession.objects.create(
            device=device, user=request.user, status="recording", start_screen=""
        )
        try:
            session.start_screen = capture_start_screen(device.device_id, session.id)
            session.save(update_fields=["start_screen", "updated_at"])
        except Exception:
            session.start_screen = ""
        broadcast_start(device.device_id, session.id)
        return Response({"id": session.id, "status": session.status}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def interrupt(self, request, pk=None):
        session = AppRecordingSession.objects.get(pk=pk, user=request.user)
        broadcast_stop(session.device.device_id)
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
        steps = list(session.steps or [])
        collapsing = _collapsible_input(steps, request.data)
        order = steps[-1].get("order") if collapsing else len(steps) + 1
        try:
            step = parse_ingested_event(request.data, order=order, template="")
        except ValueError:
            return Response({"message": "未知事件类型"}, status=status.HTTP_400_BAD_REQUEST)
        bounds = step.get("bounds") or {}
        if bounds_complete(bounds):
            step["template"] = _template_for_step(session.device.device_id, session.id, order, bounds)
        if collapsing:
            step = _merge_input(steps[-1], step)
            steps[-1] = step
        else:
            steps.append(step)
        if step.get("screen"):
            session.screen = step["screen"]
        session.steps = steps
        session.save(update_fields=["steps", "screen", "updated_at"])
        return Response(step, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def assertions(self, request, pk=None):
        session = AppRecordingSession.objects.get(pk=pk, user=request.user)
        texts = request.data.get("expected_texts") or []
        selectors = request.data.get("expected_selectors") or []
        if not texts and not selectors:
            return Response({"message": "请勾选要校验的文字或控件"}, status=status.HTTP_400_BAD_REQUEST)
        order = len(session.steps) + 1
        step = {
            "type": "assert",
            "platform": "android",
            "accessibility_id": "",
            "order": order,
            "name": "断言",
            "expected_texts": texts,
            "expected_selectors": selectors,
            "template": _template_for_step(session.device.device_id, session.id, order),
            "screen": session.screen,
        }
        session.steps = list(session.steps) + [step]
        session.save(update_fields=["steps", "updated_at"])
        return Response(step, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def stop(self, request, pk=None):
        session = AppRecordingSession.objects.get(pk=pk, user=request.user)
        broadcast_stop(session.device.device_id)
        session.status = "stopped"
        session.save(update_fields=["status", "updated_at"])
        if session.device.locked_by_id == request.user.id:
            session.device.unlock()
        return Response({"id": session.id, "steps": session.steps})

    @action(detail=True, methods=["post"])
    def save(self, request, pk=None):
        session = AppRecordingSession.objects.get(pk=pk, user=request.user)
        steps = request.data.get("steps", session.steps)
        name = request.data.get("name") or "未命名录制"
        event_chain = {"platform": "android", "screen": session.screen, "steps": steps}
        case_id = request.data.get("case_id")
        if case_id is not None:
            try:
                case = AppTestCase.objects.get(pk=case_id, created_by=request.user)
            except AppTestCase.DoesNotExist:
                return Response({"message": "用例不存在"}, status=status.HTTP_404_NOT_FOUND)
            case.name = name
            case.event_chain = event_chain
            case.start_screen = copy_case_start_screen(session.start_screen, case.id)
            case.save(update_fields=["name", "event_chain", "start_screen"])
            response_status = status.HTTP_200_OK
        else:
            case = AppTestCase.objects.create(
                name=name,
                event_chain=event_chain,
                start_screen="",
                ui_flow={},
                created_by=request.user,
            )
            case.start_screen = copy_case_start_screen(session.start_screen, case.id)
            case.save(update_fields=["start_screen"])
            response_status = status.HTTP_201_CREATED
        empty_inputs = [step for step in steps if step.get("type") == "input" and step.get("password") and not step.get("input_text")]
        return Response(
            {"id": case.id, "empty_password_steps": [step.get("order") for step in empty_inputs]},
            status=response_status,
        )

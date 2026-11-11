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
    read_ui_dump,
    save_step_image,
    service_enabled,
)
from ..recording.page_signature import capture_page, event_chain_document, merge_screen, remember_after
from ..recording.screen_labels import controls_from_dump
from ..recording.ingest import (
    absorb_typing_clicks,
    apply_control_label,
    finger_points,
    parse_ingested_event,
    place_input,
    touch_point,
)
from ..recording.touch_listener import start_touch_listener, stop_touch_listener


def _seal_steps(session, steps):
    try:
        remember_after(steps, controls_from_dump(read_ui_dump(session.device.device_id)))
    except Exception:
        return steps
    return steps


def _template_for_step(device_id, session_id, order, bounds=None):
    try:
        return save_step_image(device_id, session_id, order, bounds=bounds)
    except Exception:
        return ""


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
            return Response({"message": "请在系统设置中打开 Hejaz 录制服务"}, status=status.HTTP_400_BAD_REQUEST)
        if not service_enabled(device.device_id):
            return Response({"message": "请在系统设置中打开 Hejaz 录制服务"}, status=status.HTTP_400_BAD_REQUEST)
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
        try:
            page = capture_page(device.device_id)
        except Exception:
            page = None
        if page:
            session.screen = {"start_page": page}
            session.save(update_fields=["screen", "updated_at"])
        broadcast_start(device.device_id, session.id)
        start_touch_listener(device.device_id, session.id)
        return Response({"id": session.id, "status": session.status}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def interrupt(self, request, pk=None):
        session = AppRecordingSession.objects.get(pk=pk, user=request.user)
        stop_touch_listener(session.id)
        broadcast_stop(session.device.device_id)
        session.steps = _seal_steps(session, list(session.steps or []))
        session.status = "interrupted"
        session.save(update_fields=["steps", "status", "updated_at"])
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
        kind = request.data.get("event_type")
        if kind in ("click", "long_press") and touch_point(request.data) is None:
            steps = list(session.steps or [])
            label = (request.data.get("text") or request.data.get("content_desc") or "").strip()
            renamed = apply_control_label(steps, kind, label, request.data.get("bounds") or {})
            if renamed is None:
                return Response({"skipped": True})
            session.steps = steps
            session.save(update_fields=["steps", "updated_at"])
            return Response(renamed)
        if kind == "swipe" and finger_points(request.data) is None:
            return Response({"skipped": True})
        steps = list(session.steps or [])
        if kind == "input":
            steps = absorb_typing_clicks(steps)
        order = len(steps) + 1
        try:
            step = parse_ingested_event(request.data, order=order, template="")
        except ValueError:
            return Response({"message": "未知事件类型"}, status=status.HTTP_400_BAD_REQUEST)
        if kind == "input":
            steps, step = place_input(steps, step)
            if step is None:
                session.steps = steps
                session.save(update_fields=["steps", "updated_at"])
                return Response({"skipped": True})
            order = step.get("order") or order
        bounds = step.get("bounds") or {}
        if bounds_complete(bounds):
            step["template"] = _template_for_step(session.device.device_id, session.id, order, bounds)
        if kind != "input":
            steps.append(step)
        if step.get("screen"):
            session.screen = merge_screen(session.screen, step["screen"])
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
        stop_touch_listener(session.id)
        broadcast_stop(session.device.device_id)
        session.steps = _seal_steps(session, list(session.steps or []))
        session.status = "stopped"
        session.save(update_fields=["steps", "status", "updated_at"])
        if session.device.locked_by_id == request.user.id:
            session.device.unlock()
        return Response({"id": session.id, "steps": session.steps})

    @action(detail=True, methods=["post"])
    def save(self, request, pk=None):
        session = AppRecordingSession.objects.get(pk=pk, user=request.user)
        steps = _seal_steps(session, list(request.data.get("steps", session.steps) or []))
        name = request.data.get("name") or "未命名录制"
        event_chain = event_chain_document(session.screen, steps)
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

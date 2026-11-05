from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient
from apps.app_automation.models import AppDevice, AppRecordingSession, AppTestCase
from apps.app_automation.recording.adb_gateway import accessibility_enabled, reverse_argument, service_enabled

class RecordingApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="recorder", password="pw")
        self.device = AppDevice.objects.create(device_id="emulator-5554", name="emu", status="available")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_service_flag_detects_component(self):
        assert accessibility_enabled("com.testhub.recorder/com.testhub.recorder.RecorderService") is True
        assert accessibility_enabled("com.other/com.other.Service") is False

    def test_service_enabled_uses_command_output_without_adb(self):
        with patch("subprocess.run") as run:
            assert service_enabled(
                "emulator-5554",
                command_output="com.testhub.recorder/com.testhub.recorder.RecorderService",
            ) is True
            assert service_enabled("emulator-5554", command_output="com.other/com.other.Service") is False
            run.assert_not_called()

    def test_reverse_argument_is_fixed_ports(self):
        assert reverse_argument(8000) == ["reverse", "tcp:27183", "tcp:8000"]

    def test_start_rejected_when_service_disabled(self):
        with patch("subprocess.run") as run:
            response = self.client.post("/api/app-automation/recording-sessions/", {"device_id": "emulator-5554"}, format="json")
            run.assert_not_called()
        assert response.status_code == 400
        assert AppRecordingSession.objects.count() == 0

    def test_start_rejected_when_device_locked_by_current_user(self):
        self.device.lock(self.user)
        with patch("subprocess.run") as run:
            response = self.client.post(
                "/api/app-automation/recording-sessions/",
                {"device_id": "emulator-5554"},
                format="json",
            )
            run.assert_not_called()
        assert response.status_code == 400
        assert AppRecordingSession.objects.count() == 0

    def test_parse_ui_dump_lists_text_and_selector(self):
        from apps.app_automation.recording.adb_gateway import parse_ui_dump
        xml = '<node text="欢迎" resource-id="com.app:id/title" content-desc="" class="TextView" bounds="[0,100][100,150]" />'
        parsed = parse_ui_dump(xml, 1080, 2400)
        assert parsed["texts"] == ["欢迎"]
        assert parsed["selectors"][0]["resource_id"] == "com.app:id/title"

    def test_interrupt_keeps_steps(self):
        session = AppRecordingSession.objects.create(
            device=self.device, user=self.user, status="recording", steps=[{"type": "click", "order": 1}]
        )
        response = self.client.post(f"/api/app-automation/recording-sessions/{session.id}/interrupt/", {}, format="json")
        assert response.status_code == 200
        session.refresh_from_db()
        assert session.status == "interrupted"
        assert session.steps[0]["type"] == "click"

    def test_save_update_with_case_id_fills_password_without_second_case(self):
        password_step = {
            "type": "input",
            "platform": "android",
            "order": 1,
            "name": "输入密码",
            "password": True,
            "input_text": "",
            "resource_id": "com.app:id/pwd",
            "template": "",
        }
        session = AppRecordingSession.objects.create(
            device=self.device,
            user=self.user,
            status="stopped",
            start_screen="start.png",
            steps=[password_step],
        )
        first = self.client.post(
            f"/api/app-automation/recording-sessions/{session.id}/save/",
            {"name": "密码用例", "steps": session.steps},
            format="json",
        )
        assert first.status_code == 201
        case_id = first.data["id"]
        assert first.data["empty_password_steps"] == [1]
        assert AppTestCase.objects.count() == 1

        filled = [{**password_step, "input_text": "secret123"}]
        second = self.client.post(
            f"/api/app-automation/recording-sessions/{session.id}/save/",
            {"name": "密码用例", "steps": filled, "case_id": case_id},
            format="json",
        )
        assert second.status_code == 200
        assert second.data["id"] == case_id
        assert second.data["empty_password_steps"] == []
        assert AppTestCase.objects.count() == 1
        case = AppTestCase.objects.get(pk=case_id)
        assert case.event_chain["steps"][0]["input_text"] == "secret123"

    def test_save_creates_case_without_touching_ui_flow(self):
        session = AppRecordingSession.objects.create(
            device=self.device,
            user=self.user,
            status="stopped",
            start_screen="start.png",
            steps=[{
                "type": "click", "platform": "android", "order": 1, "name": "点击 登录",
                "resource_id": "com.app:id/login", "template": "t.png", "input_text": "",
            }],
        )
        response = self.client.post(
            f"/api/app-automation/recording-sessions/{session.id}/save/",
            {"name": "登录用例", "steps": session.steps},
            format="json",
        )
        assert response.status_code == 201
        case = AppTestCase.objects.get(name="登录用例")
        assert case.event_chain["steps"][0]["resource_id"] == "com.app:id/login"
        assert case.start_screen == "start.png"
        assert case.ui_flow == {}

    def test_events_accepts_unauthenticated_click(self):
        session = AppRecordingSession.objects.create(
            device=self.device, user=self.user, status="recording"
        )
        guest = APIClient()
        response = guest.post(
            f"/api/app-automation/recording-sessions/{session.id}/events/",
            {
                "event_type": "click",
                "resource_id": "com.app:id/login",
                "content_desc": "",
                "text": "登录",
                "class_name": "Button",
                "bounds": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.1},
                "screen": {"width": 1080, "height": 2400},
                "duration_ms": 80,
            },
            format="json",
        )
        assert response.status_code == 201
        session.refresh_from_db()
        assert len(session.steps) == 1
        assert session.steps[0]["type"] == "click"
        assert session.steps[0]["resource_id"] == "com.app:id/login"

    def test_unknown_event_returns_400(self):
        session = AppRecordingSession.objects.create(
            device=self.device, user=self.user, status="recording"
        )
        guest = APIClient()
        response = guest.post(
            f"/api/app-automation/recording-sessions/{session.id}/events/",
            {"event_type": "rotate"},
            format="json",
        )
        assert response.status_code == 400
        session.refresh_from_db()
        assert session.steps == []

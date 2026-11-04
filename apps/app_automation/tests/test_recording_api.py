from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient
from apps.app_automation.models import AppDevice, AppRecordingSession, AppTestCase
from apps.app_automation.recording.adb_gateway import accessibility_enabled

class RecordingApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="recorder", password="pw")
        self.device = AppDevice.objects.create(device_id="emulator-5554", name="emu", status="available")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_service_flag_detects_component(self):
        assert accessibility_enabled("com.testhub.recorder/com.testhub.recorder.RecorderService") is True
        assert accessibility_enabled("com.other/com.other.Service") is False

    def test_start_rejected_when_service_disabled(self):
        response = self.client.post("/api/app-automation/recording-sessions/", {"device_id": "emulator-5554"}, format="json")
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

import os
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from apps.app_automation.models import AppDevice, AppRecordingSession, AppTestCase, AppTestExecution
from apps.app_automation.recording.adb_gateway import (
    accessibility_enabled,
    reverse_argument,
    service_enabled,
    start_broadcast_args,
    stop_broadcast_args,
)

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

    def test_broadcast_arguments_name_session_without_device(self):
        start = start_broadcast_args("emulator-5554", 42)
        assert start[:6] == ["adb", "-s", "emulator-5554", "shell", "am", "broadcast"]
        assert "com.testhub.recorder.START" in start
        assert start[-1] == "http://127.0.0.1:27183/api/app-automation/recording-sessions/42/events/"
        stop = stop_broadcast_args("emulator-5554")
        assert stop[-1] == "com.testhub.recorder.STOP"
        assert "42" not in stop

    @override_settings(APP_RECORDER_SERVICE_ENABLED=False)
    def test_start_rejected_when_service_disabled(self):
        with patch("subprocess.run") as run, patch("subprocess.check_output") as output:
            response = self.client.post("/api/app-automation/recording-sessions/", {"device_id": "emulator-5554"}, format="json")
            run.assert_not_called()
            output.assert_not_called()
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
        with patch("subprocess.check_output", side_effect=OSError("no device")):
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

    def test_missing_flag_rejects_closed_service_without_reverse_or_session(self):
        def fake_run(args, **kwargs):
            class Result:
                returncode = 0
                stdout = b"com.other/com.other.Service"
            return Result()

        with patch("subprocess.run", side_effect=fake_run) as run, patch("subprocess.check_output") as output:
            response = self.client.post(
                "/api/app-automation/recording-sessions/",
                {"device_id": "emulator-5554"},
                format="json",
            )
        assert response.status_code == 400
        assert AppRecordingSession.objects.count() == 0
        commands = [list(call.args[0]) for call in run.call_args_list]
        assert any("enabled_accessibility_services" in command for command in commands)
        assert all("reverse" not in command for command in commands)
        output.assert_not_called()

    def test_start_broadcasts_when_service_enabled_and_stop_broadcasts(self):
        component = b"com.testhub.recorder/com.testhub.recorder.RecorderService"

        def fake_run(args, **kwargs):
            class Result:
                returncode = 0
                stdout = component
            return Result()

        with patch("subprocess.run", side_effect=fake_run) as run, patch("subprocess.check_output", return_value=b"png"):
            response = self.client.post(
                "/api/app-automation/recording-sessions/",
                {"device_id": "emulator-5554"},
                format="json",
            )
            assert response.status_code == 201
            session_id = response.data["id"]
            commands = [list(call.args[0]) for call in run.call_args_list]
            reverse = ["adb", "-s", "emulator-5554", "reverse", "tcp:27183", "tcp:8000"]
            assert reverse in commands
            start = [command for command in commands if "com.testhub.recorder.START" in command]
            assert len(start) == 1
            assert start[0][-1] == "http://127.0.0.1:27183/api/app-automation/recording-sessions/%s/events/" % session_id
            assert commands.index(reverse) < commands.index(start[0])
            session = AppRecordingSession.objects.get(pk=session_id)
            normalized = session.start_screen.replace("\\", "/")
            assert normalized.endswith("recordings/sessions/%s.png" % session_id)
            run.reset_mock()
            stopped = self.client.post(
                "/api/app-automation/recording-sessions/%s/stop/" % session_id,
                {},
                format="json",
            )
            assert stopped.status_code == 200
            stop_commands = [list(call.args[0]) for call in run.call_args_list]
            assert ["adb", "-s", "emulator-5554", "shell", "am", "broadcast", "-a", "com.testhub.recorder.STOP"] in stop_commands

    def test_interrupt_broadcasts_stop(self):
        session = AppRecordingSession.objects.create(
            device=self.device, user=self.user, status="recording", steps=[{"type": "click", "order": 1}]
        )
        with patch("subprocess.run") as run:
            response = self.client.post(
                "/api/app-automation/recording-sessions/%s/interrupt/" % session.id,
                {},
                format="json",
            )
        assert response.status_code == 200
        commands = [list(call.args[0]) for call in run.call_args_list]
        assert ["adb", "-s", "emulator-5554", "shell", "am", "broadcast", "-a", "com.testhub.recorder.STOP"] in commands

    def test_consecutive_inputs_collapse_to_latest_text(self):
        session = AppRecordingSession.objects.create(
            device=self.device, user=self.user, status="recording"
        )
        guest = APIClient()
        url = "/api/app-automation/recording-sessions/%s/events/" % session.id
        first = guest.post(url, {
            "event_type": "input",
            "resource_id": "com.app:id/name",
            "text": "a",
            "input_text": "a",
        }, format="json")
        second = guest.post(url, {
            "event_type": "input",
            "resource_id": "com.app:id/name",
            "text": "abcd",
            "input_text": "abcd",
        }, format="json")
        assert first.status_code == 201
        assert second.status_code == 201
        session.refresh_from_db()
        assert len(session.steps) == 1
        assert session.steps[0]["input_text"] == "abcd"
        assert session.steps[0]["order"] == 1
        other = guest.post(url, {
            "event_type": "input",
            "resource_id": "com.app:id/other",
            "input_text": "zz",
        }, format="json")
        assert other.status_code == 201
        guest.post(url, {"event_type": "click", "resource_id": "com.app:id/name", "text": "确定"}, format="json")
        guest.post(url, {
            "event_type": "input",
            "resource_id": "com.app:id/name",
            "input_text": "next",
        }, format="json")
        session.refresh_from_db()
        assert [step["type"] for step in session.steps] == ["input", "input", "click", "input"]
        assert session.steps[0]["input_text"] == "abcd"
        assert session.steps[1]["input_text"] == "zz"
        assert session.steps[3]["input_text"] == "next"

    def test_event_bounds_store_cropped_template_without_device(self):
        cv2 = pytest_cv2()
        if cv2 is None:
            return
        import numpy as np
        image = np.zeros((100, 200, 3), dtype=np.uint8)
        image[20:40, 50:90] = (1, 2, 3)
        ok, encoded = cv2.imencode(".png", image)
        assert ok
        session = AppRecordingSession.objects.create(
            device=self.device, user=self.user, status="recording"
        )
        guest = APIClient()
        with patch("subprocess.check_output", return_value=encoded.tobytes()):
            response = guest.post(
                "/api/app-automation/recording-sessions/%s/events/" % session.id,
                {
                    "event_type": "click",
                    "resource_id": "com.app:id/login",
                    "text": "登录",
                    "bounds": {"x": 0.25, "y": 0.2, "w": 0.2, "h": 0.2},
                    "screen": {"width": 200, "height": 100},
                },
                format="json",
            )
        assert response.status_code == 201
        template = response.data["template"].replace("\\", "/")
        assert "/sessions/%s/1.png" % session.id in template
        decoded = cv2.imdecode(np.fromfile(response.data["template"], dtype=np.uint8), cv2.IMREAD_COLOR)
        assert decoded.shape[:2] == (20, 40)
        assert tuple(int(value) for value in decoded[0, 0]) == (1, 2, 3)

    def test_capture_failure_still_stores_step(self):
        session = AppRecordingSession.objects.create(
            device=self.device, user=self.user, status="recording"
        )
        guest = APIClient()
        with patch("subprocess.check_output", side_effect=OSError("adb missing")):
            response = guest.post(
                "/api/app-automation/recording-sessions/%s/events/" % session.id,
                {
                    "event_type": "click",
                    "resource_id": "com.app:id/login",
                    "bounds": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.1},
                },
                format="json",
            )
        assert response.status_code == 201
        assert response.data["template"] == ""
        session.refresh_from_db()
        assert len(session.steps) == 1

    def test_assertion_saves_full_screen_and_keeps_step_when_capture_fails(self):
        session = AppRecordingSession.objects.create(
            device=self.device, user=self.user, status="recording", steps=[]
        )
        png = b"\x89PNG\r\nfull-screen"
        with patch("subprocess.check_output", return_value=png):
            saved = self.client.post(
                "/api/app-automation/recording-sessions/%s/assertions/" % session.id,
                {"expected_texts": ["欢迎"]},
                format="json",
            )
        assert saved.status_code == 201
        assert saved.data["template"].replace("\\", "/").endswith("/sessions/%s/1.png" % session.id)
        with open(saved.data["template"], "rb") as handle:
            assert handle.read() == png
        with patch("subprocess.check_output", side_effect=OSError("adb missing")):
            failed = self.client.post(
                "/api/app-automation/recording-sessions/%s/assertions/" % session.id,
                {"expected_texts": ["再见"]},
                format="json",
            )
        assert failed.status_code == 201
        assert failed.data["template"] == ""
        session.refresh_from_db()
        assert len(session.steps) == 2

    def test_second_recording_does_not_overwrite_other_case_start(self):
        from django.conf import settings
        directory = os.path.join(settings.MEDIA_ROOT, "app-automation", "recordings", "sessions")
        os.makedirs(directory, exist_ok=True)
        first_src = os.path.join(directory, "case-copy-a.png")
        second_src = os.path.join(directory, "case-copy-b.png")
        with open(first_src, "wb") as handle:
            handle.write(b"first-screen")
        with open(second_src, "wb") as handle:
            handle.write(b"second-screen")
        first = AppRecordingSession.objects.create(
            device=self.device, user=self.user, status="stopped", start_screen=first_src, steps=[]
        )
        second = AppRecordingSession.objects.create(
            device=self.device, user=self.user, status="stopped", start_screen=second_src, steps=[]
        )
        saved_first = self.client.post(
            "/api/app-automation/recording-sessions/%s/save/" % first.id,
            {"name": "第一屏", "steps": []},
            format="json",
        )
        saved_second = self.client.post(
            "/api/app-automation/recording-sessions/%s/save/" % second.id,
            {"name": "第二屏", "steps": []},
            format="json",
        )
        assert saved_first.status_code == 201
        assert saved_second.status_code == 201
        case_one = AppTestCase.objects.get(pk=saved_first.data["id"])
        case_two = AppTestCase.objects.get(pk=saved_second.data["id"])
        assert case_one.start_screen.replace("\\", "/").endswith("/%s/start.png" % case_one.id)
        assert case_two.start_screen.replace("\\", "/").endswith("/%s/start.png" % case_two.id)
        with open(case_one.start_screen, "rb") as handle:
            assert handle.read() == b"first-screen"
        with open(case_two.start_screen, "rb") as handle:
            assert handle.read() == b"second-screen"

    def test_mismatch_copies_media_urls(self):
        from django.conf import settings
        from apps.app_automation.runners.event_chain_runner import EventChainRunner
        case = AppTestCase.objects.create(
            name="不匹配", event_chain={"steps": [{"type": "click", "order": 1}]}, ui_flow={}, created_by=self.user
        )
        execution = AppTestExecution.objects.create(
            test_case=case, device=self.device, user=self.user, status="running"
        )
        source = os.path.join(settings.MEDIA_ROOT, "app-automation", "recordings", "sessions")
        os.makedirs(source, exist_ok=True)
        current = os.path.join(source, "mismatch-current-src.png")
        expected = os.path.join(source, "mismatch-expected-src.png")
        with open(current, "wb") as handle:
            handle.write(b"current-bytes")
        with open(expected, "wb") as handle:
            handle.write(b"expected-bytes")
        case.start_screen = expected
        case.save(update_fields=["start_screen"])

        class Shot:
            def screenshot(self, name):
                return current

            def match_images(self, *args, **kwargs):
                return False

        EventChainRunner().run(execution.id, device=Shot())
        execution.refresh_from_db()
        assert execution.error_message == "开始界面不匹配"
        assert execution.mismatch_current_url.startswith("/media/")
        assert execution.mismatch_expected_url.startswith("/media/")
        assert execution.mismatch_current_url.endswith("/mismatch-current.png")
        assert execution.mismatch_expected_url.endswith("/mismatch-expected.png")
        assert ":\\" not in execution.mismatch_current_url
        result_dir = os.path.join(settings.MEDIA_ROOT, "app-automation", "results", str(execution.id))
        with open(os.path.join(result_dir, "mismatch-current.png"), "rb") as handle:
            assert handle.read() == b"current-bytes"
        with open(os.path.join(result_dir, "mismatch-expected.png"), "rb") as handle:
            assert handle.read() == b"expected-bytes"


def pytest_cv2():
    try:
        import cv2
    except ImportError:
        return None
    return cv2

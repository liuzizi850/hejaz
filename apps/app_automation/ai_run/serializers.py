# -*- coding: utf-8 -*-
from rest_framework import serializers

from .models import AiRunExecution, AiRunScript
from .reports import share_url_path


class AiRunScriptSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField()
    source = serializers.SerializerMethodField()

    class Meta:
        model = AiRunScript
        fields = ("id", "name", "source", "original_name", "created_at")

    def get_id(self, obj):
        return f"upload:{obj.id}"

    def get_name(self, obj):
        return obj.display_name or obj.original_name

    def get_source(self, obj):
        return "upload"


class AiRunExecutionSerializer(serializers.ModelSerializer):
    report_available = serializers.SerializerMethodField()
    cases = serializers.SerializerMethodField()
    # "success" is accepted as a tester-facing alias of completed in some wording.
    status_display = serializers.SerializerMethodField()

    class Meta:
        model = AiRunExecution
        fields = (
            "id",
            "serial",
            "status",
            "status_display",
            "result",
            "script_ids",
            "cases",
            "error_message",
            "report_available",
            "started_at",
            "finished_at",
            "created_at",
        )

    def get_status_display(self, obj):
        if obj.status == AiRunExecution.STATUS_COMPLETED:
            return "completed"
        return obj.status

    def get_report_available(self, obj):
        return obj.status == AiRunExecution.STATUS_COMPLETED and bool(obj.report_relpath)

    def get_cases(self, obj):
        run_id = obj.id
        cases = []
        for case in obj.case_results or []:
            shots = []
            for rel in case.get("screenshots") or []:
                if not isinstance(rel, str) or not rel or ".." in rel or rel.startswith("/"):
                    continue
                shots.append(f"/api/app-automation/ai-runs/runs/{run_id}/report/{rel}")
            cases.append(
                {
                    "id": case.get("id") or "",
                    "name": case.get("name") or "",
                    "status": case.get("status") or "",
                    "failure_reason": case.get("failure_reason") or "",
                    "screenshots": shots,
                }
            )
        return cases


class CreateAiRunSerializer(serializers.Serializer):
    serial = serializers.CharField(max_length=255)
    script_ids = serializers.ListField(child=serializers.CharField(max_length=200), allow_empty=False)


class ShareSerializer(serializers.Serializer):
    token = serializers.CharField()
    url = serializers.SerializerMethodField()

    def get_url(self, obj):
        token = obj["token"] if isinstance(obj, dict) else obj.token
        return share_url_path(token)

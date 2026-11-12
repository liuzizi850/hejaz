from rest_framework import serializers

from apps.code_monitor.acquire import AcquireError, ensure_http_git_url
from apps.code_monitor.models import CodeAddress, ScanTask


class CodeAddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = CodeAddress
        fields = ["id", "name", "git_url", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate_git_url(self, value):
        try:
            return ensure_http_git_url(value)
        except AcquireError as exc:
            raise serializers.ValidationError(str(exc)) from exc


class ScanTaskSerializer(serializers.ModelSerializer):
    model_config_name = serializers.CharField(source="model_config.name", read_only=True)
    has_result = serializers.SerializerMethodField()

    class Meta:
        model = ScanTask
        fields = [
            "id", "source_type", "task_type", "requirement_text", "git_url",
            "model_config", "model_config_name", "status", "progress",
            "error_message", "has_result", "created_at",
        ]
        read_only_fields = fields

    def get_has_result(self, obj):
        return bool(obj.result_file)

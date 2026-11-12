# -*- coding: utf-8 -*-
"""Minimal REQ-002 models: uploaded scripts, execution records, share tokens.

These are independent of the existing case/suite/Allure tables.
"""
import secrets
import uuid

from django.conf import settings
from django.db import models


def _new_view_token() -> str:
    return secrets.token_urlsafe(32)


def _new_share_token() -> str:
    return secrets.token_urlsafe(32)


class AiRunScript(models.Model):
    """A tester-uploaded .feature stored under the app data directory."""

    SOURCE_UPLOAD = "upload"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ai_run_scripts",
        verbose_name="上传用户",
    )
    original_name = models.CharField(max_length=255, verbose_name="原始文件名")
    display_name = models.CharField(max_length=255, blank=True, default="", verbose_name="展示名称")
    relative_path = models.CharField(max_length=500, verbose_name="相对存储路径")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        db_table = "app_ai_run_scripts"
        verbose_name = "AI执行上传脚本"
        verbose_name_plural = "AI执行上传脚本"
        ordering = ["-created_at"]

    def __str__(self):
        return self.display_name or self.original_name


class AiRunExecution(models.Model):
    """One page-triggered execution of selected BDD scripts on a connected device."""

    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    # Alias accepted in some product wording; stored value is completed/failed.
    STATUS_SUCCESS = "success"

    STATUS_CHOICES = [
        (STATUS_PENDING, "待执行"),
        (STATUS_RUNNING, "进行中"),
        (STATUS_COMPLETED, "已完成"),
        (STATUS_FAILED, "失败"),
    ]

    RESULT_PASSED = "passed"
    RESULT_FAILED = "failed"

    RESULT_CHOICES = [
        (RESULT_PASSED, "通过"),
        (RESULT_FAILED, "失败"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_run_executions",
        verbose_name="执行用户",
    )
    serial = models.CharField(max_length=255, verbose_name="设备序列号")
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        verbose_name="平台执行状态",
    )
    result = models.CharField(
        max_length=20,
        choices=RESULT_CHOICES,
        null=True,
        blank=True,
        default=None,
        verbose_name="夹具结果",
        help_text="编排成功后填写；仅夹具断言失败时平台状态仍为已完成",
    )
    script_ids = models.JSONField(default=list, verbose_name="所选脚本标识")
    case_results = models.JSONField(default=list, verbose_name="用例结果摘要")
    report_relpath = models.CharField(max_length=500, blank=True, default="", verbose_name="报告相对目录")
    error_message = models.TextField(blank=True, default="", verbose_name="错误信息")
    view_token = models.CharField(max_length=64, default=_new_view_token, unique=True, verbose_name="页面查看令牌")
    celery_task_id = models.CharField(max_length=255, blank=True, default="", verbose_name="Celery任务ID")
    started_at = models.DateTimeField(null=True, blank=True, verbose_name="开始时间")
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name="结束时间")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "app_ai_run_executions"
        verbose_name = "AI执行记录"
        verbose_name_plural = "AI执行记录"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self):
        return f"ai-run-{self.id} ({self.status})"


class AiRunShare(models.Model):
    """Unguessable read-only share token for one execution report. No expiry this period."""

    execution = models.ForeignKey(
        AiRunExecution,
        on_delete=models.CASCADE,
        related_name="shares",
        verbose_name="执行记录",
    )
    token = models.CharField(max_length=64, unique=True, default=_new_share_token, verbose_name="分享令牌")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_run_shares",
        verbose_name="创建人",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        db_table = "app_ai_run_shares"
        verbose_name = "AI执行报告分享"
        verbose_name_plural = "AI执行报告分享"
        ordering = ["-created_at"]

    def __str__(self):
        return f"share-{self.id}"

from django.conf import settings
from django.db import models


class CodeAddress(models.Model):
    name = models.CharField(max_length=200, verbose_name="名称")
    git_url = models.CharField(max_length=500, verbose_name="Git 地址")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="code_monitor_addresses",
        verbose_name="创建者",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        db_table = "code_monitor_addresses"
        ordering = ["-created_at"]


class ScanTask(models.Model):
    SOURCE_GIT = "git"
    SOURCE_ZIP = "zip"
    SOURCE_CHOICES = [
        (SOURCE_GIT, "Git"),
        (SOURCE_ZIP, "zip"),
    ]
    TASK_API_EXTRACT = "api_extract"
    TASK_REQUIREMENT_REVIEW = "requirement_review"
    TASK_TYPE_CHOICES = [
        (TASK_API_EXTRACT, "提取 API"),
        (TASK_REQUIREMENT_REVIEW, "需求检查"),
    ]
    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_SUCCEEDED = "succeeded"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "待执行"),
        (STATUS_RUNNING, "执行中"),
        (STATUS_SUCCEEDED, "成功"),
        (STATUS_FAILED, "失败"),
    ]

    source_type = models.CharField(max_length=10, choices=SOURCE_CHOICES, verbose_name="来源类型")
    task_type = models.CharField(
        max_length=32,
        choices=TASK_TYPE_CHOICES,
        default=TASK_API_EXTRACT,
        verbose_name="任务类型",
    )
    requirement_text = models.TextField(blank=True, default="", verbose_name="需求原文")
    git_url = models.CharField(max_length=500, blank=True, default="", verbose_name="Git 地址")
    archive = models.FileField(upload_to="code_monitor/archives/", null=True, blank=True, verbose_name="上传的 zip")
    model_config = models.ForeignKey(
        "requirement_analysis.AIModelConfig",
        on_delete=models.PROTECT,
        related_name="code_monitor_tasks",
        verbose_name="AI 模型配置",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, verbose_name="状态")
    progress = models.PositiveSmallIntegerField(default=0, verbose_name="进度")
    error_message = models.TextField(blank=True, default="", verbose_name="失败原因")
    celery_task_id = models.CharField(max_length=100, blank=True, default="", verbose_name="Celery 任务 ID")
    result_file = models.FileField(upload_to="code_monitor/results/", null=True, blank=True, verbose_name="结果 Excel")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="code_monitor_tasks",
        verbose_name="创建者",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "code_monitor_tasks"
        ordering = ["-created_at"]

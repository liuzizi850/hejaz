# -*- coding: utf-8 -*-
from django.urls import path, re_path

from . import views

urlpatterns = [
    path("scripts/", views.AiRunScriptListView.as_view(), name="ai-run-scripts"),
    path("scripts/upload/", views.AiRunScriptUploadView.as_view(), name="ai-run-script-upload"),
    path("devices/", views.AiRunDeviceListView.as_view(), name="ai-run-devices"),
    path("runs/", views.AiRunListCreateView.as_view(), name="ai-run-runs"),
    path("runs/<int:run_id>/", views.AiRunDetailView.as_view(), name="ai-run-detail"),
    path("runs/<int:run_id>/download/", views.AiRunDownloadView.as_view(), name="ai-run-download"),
    path("runs/<int:run_id>/share/", views.AiRunShareCreateView.as_view(), name="ai-run-share-create"),
    # Path-token report URLs (same style as share): relative screenshot srcs inherit the token segment.
    re_path(
        r"^runs/(?P<run_id>\d+)/report/(?P<view_token>[A-Za-z0-9_\-]+)/(?P<file_path>.*)$",
        views.AiRunReportView.as_view(),
        name="ai-run-report-token-file",
    ),
    path(
        "runs/<int:run_id>/report/<str:view_token>/",
        views.AiRunReportView.as_view(),
        name="ai-run-report-token",
    ),
    path("runs/<int:run_id>/report/", views.AiRunReportView.as_view(), name="ai-run-report"),
    re_path(
        r"^share/(?P<token>[A-Za-z0-9_\-]+)/(?P<file_path>.*)$",
        views.AiRunShareReportView.as_view(),
        name="ai-run-share-file",
    ),
    path("share/<str:token>/", views.AiRunShareReportView.as_view(), name="ai-run-share"),
]

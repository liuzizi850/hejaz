from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.code_monitor.views import CodeAddressViewSet, ScanTaskViewSet

router = DefaultRouter()
router.register(r"addresses", CodeAddressViewSet, basename="code-monitor-address")
router.register(r"tasks", ScanTaskViewSet, basename="code-monitor-task")

urlpatterns = [
    path("", include(router.urls)),
]

# -*- coding: utf-8 -*-
"""Detect whether the async execution worker is reachable."""
from __future__ import annotations

import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def celery_workers_ready(inspect_fn=None) -> bool:
    """Return True when tasks can be executed.

    In tests (CELERY_TASK_ALWAYS_EAGER) the worker is considered ready.
    Otherwise require a successful inspect ping from at least one worker.
    """
    if inspect_fn is None and getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        return True
    try:
        if inspect_fn is not None:
            ping = inspect_fn()
        else:
            from celery import current_app

            inspector = current_app.control.inspect(timeout=1.0)
            ping = inspector.ping() if inspector is not None else None
        return bool(ping)
    except Exception:
        logger.info("REQ-002 celery inspect failed; treating workers as not ready")
        return False

# -*- coding: utf-8 -*-
"""Celery task for REQ-002 page runs. Does not use the UI Flow / Allure executor."""
from celery import shared_task


@shared_task
def execute_ai_run_task(run_id):
    from .execution import execute_run

    execute_run(run_id)

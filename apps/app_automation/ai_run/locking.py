# -*- coding: utf-8 -*-
"""Reuse existing AppDevice lock around a single-device page run."""
from __future__ import annotations

import logging
from contextlib import contextmanager

from django.db import transaction
from django.utils import timezone

from ..constants import DeviceStatus
from ..models import AppDevice
from .constants import DEVICE_LOCKED

logger = logging.getLogger(__name__)


def _classify_connection(serial: str) -> str:
    if serial.startswith("emulator-"):
        return "emulator"
    if ":" in serial:
        return "remote_emulator"
    return "real_device"


@contextmanager
def locked_device(serial: str, user):
    """Lock the AppDevice row for `serial`, creating a row if needed. Always release."""
    with transaction.atomic():
        device, _created = AppDevice.objects.select_for_update().get_or_create(
            device_id=serial,
            defaults={
                "name": serial,
                "status": DeviceStatus.ONLINE,
                "connection_type": _classify_connection(serial),
            },
        )
        if device.status == DeviceStatus.LOCKED and device.locked_by_id and device.locked_by_id != getattr(user, "id", None):
            if not device.is_lock_expired():
                raise RuntimeError(DEVICE_LOCKED)
        device.lock(user)
    try:
        yield device
    finally:
        try:
            device.refresh_from_db()
            if device.locked_by_id == getattr(user, "id", None) or device.status == DeviceStatus.LOCKED:
                # Release even if status drifted; only unlock when we still own it or lock is stale.
                if device.locked_by_id in (getattr(user, "id", None), None) or device.is_lock_expired():
                    device.unlock()
                    # After a successful page run the device is still online, not merely "available".
                    if device.status == DeviceStatus.AVAILABLE:
                        device.status = DeviceStatus.ONLINE
                        device.save(update_fields=["status"])
        except Exception:
            logger.exception("REQ-002 failed to release device lock")

# -*- coding: utf-8 -*-
import cv2
import numpy as np


def _window(image, x, y, width_ratio, height_ratio):
    height, width = image.shape[:2]
    box_w = max(int(round(width * width_ratio)), 8)
    box_h = max(int(round(height * height_ratio)), 8)
    center_x = int(round(float(x) * width))
    center_y = int(round(float(y) * height))
    left = max(0, center_x - box_w // 2)
    top = max(0, center_y - box_h // 2)
    right = min(width, left + box_w)
    bottom = min(height, top + box_h)
    left = max(0, right - box_w)
    top = max(0, bottom - box_h)
    crop = image[top:bottom, left:right].copy()
    if crop.size == 0 or crop.shape[0] < 8 or crop.shape[1] < 8:
        return None
    return crop


def locate_icon(source, screen, x, y, width_ratio=0.12, height_ratio=0.07, threshold=0.8):
    """Find the icon around a recorded point on the current screen.

    Returns the match center as ratios, or None when the icon is not visible.
    """
    if source is None or screen is None:
        return None
    if not isinstance(source, np.ndarray) or not isinstance(screen, np.ndarray):
        return None
    try:
        px = float(x)
        py = float(y)
    except (TypeError, ValueError):
        return None
    crop = _window(source, px, py, width_ratio, height_ratio)
    if crop is None or crop.shape[0] >= screen.shape[0] or crop.shape[1] >= screen.shape[1]:
        return None
    result = cv2.matchTemplate(screen, crop, cv2.TM_CCOEFF_NORMED)
    _min_value, max_value, _min_at, max_at = cv2.minMaxLoc(result)
    if float(max_value) < threshold:
        return None
    center_x = max_at[0] + crop.shape[1] / 2.0
    center_y = max_at[1] + crop.shape[0] / 2.0
    return center_x / float(screen.shape[1]), center_y / float(screen.shape[0])

import numpy as np

from apps.app_automation.recording.icon_locate import locate_icon


def _patch():
    patch = np.zeros((24, 24, 3), dtype=np.uint8)
    patch[:, :, 1] = 210
    patch[4:20, 4:20, 2] = 160
    return patch


def test_locate_icon_finds_the_same_icon_after_it_moves():
    source = np.zeros((220, 180, 3), dtype=np.uint8)
    source[:, :] = (30, 40, 50)
    source[40:64, 70:94] = _patch()
    screen = np.zeros_like(source)
    screen[:, :] = (30, 40, 50)
    screen[120:144, 20:44] = _patch()
    found = locate_icon(source, screen, 82 / 180, 52 / 220, width_ratio=0.16, height_ratio=0.14)
    assert found is not None
    assert abs(found[0] - (32 / 180)) < 0.03
    assert abs(found[1] - (132 / 220)) < 0.03


def test_locate_icon_rejects_a_different_picture():
    source = np.zeros((220, 180, 3), dtype=np.uint8)
    source[:, :] = (30, 40, 50)
    source[40:64, 70:94] = _patch()
    screen = np.zeros_like(source)
    screen[:, :] = (30, 40, 50)
    other = _patch()
    other[:, :, 0] = 220
    other[:, :, 1] = 20
    screen[120:144, 20:44] = other
    assert locate_icon(source, screen, 82 / 180, 52 / 220, width_ratio=0.16, height_ratio=0.14) is None

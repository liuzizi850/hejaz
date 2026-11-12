# -*- coding: utf-8 -*-


def search_for_icon(locate, home, swipe, page_limit=3, drawer_limit=4):
    """Look through the launcher for an icon that is not on the current screen.

    ``locate`` returns a point or None. ``home`` goes to the launcher.
    ``swipe`` takes ``left``, ``right``, or ``up``.
    """
    home()
    found = locate()
    if found:
        return found
    for _ in range(page_limit):
        swipe("left")
        found = locate()
        if found:
            return found
    for _ in range(page_limit * 2):
        swipe("right")
        found = locate()
        if found:
            return found
    home()
    for _ in range(drawer_limit):
        swipe("up")
        found = locate()
        if found:
            return found
    return None

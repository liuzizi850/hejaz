from apps.app_automation.recording.app_seek import search_for_icon


def test_search_stops_on_the_home_page_that_shows_the_icon():
    calls = []
    answers = iter([None, (0.4, 0.2)])

    def locate():
        calls.append("locate")
        return next(answers)

    def home():
        calls.append("home")

    def swipe(direction):
        calls.append(direction)

    assert search_for_icon(locate, home, swipe, page_limit=3) == (0.4, 0.2)
    assert calls == ["home", "locate", "left", "locate"]


def test_search_gives_up_after_the_launcher_pages_and_the_drawer():
    calls = []

    def swipe(direction):
        calls.append(direction)

    assert search_for_icon(lambda: None, lambda: calls.append("home"), swipe, page_limit=2, drawer_limit=2) is None
    assert calls.count("home") == 2
    assert calls.count("left") == 2
    assert calls.count("right") == 4
    assert calls.count("up") == 2

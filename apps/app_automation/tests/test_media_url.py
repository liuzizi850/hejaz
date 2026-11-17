import os

from apps.app_automation.recording.adb_gateway import resolve_media_file, to_media_url


def test_report_media_outside_worktree_still_has_a_url(tmp_path, settings):
    repo = tmp_path / "repo"
    worktree = repo / ".worktrees" / "main"
    shot_dir = repo / "media" / "app-automation" / "results" / "47"
    shot_dir.mkdir(parents=True)
    shot = shot_dir / "1-click.png"
    shot.write_bytes(b"png")
    (worktree / "media").mkdir(parents=True)
    settings.BASE_DIR = worktree
    settings.MEDIA_ROOT = str(worktree / "media")
    settings.MEDIA_URL = "/media/"

    assert to_media_url(str(shot)) == "/media/app-automation/results/47/1-click.png"
    found = resolve_media_file("app-automation/results/47/1-click.png")
    assert os.path.normcase(found) == os.path.normcase(str(shot))


def test_media_url_rejects_paths_outside_known_roots(tmp_path, settings):
    worktree = tmp_path / "repo" / ".worktrees" / "main"
    (worktree / "media").mkdir(parents=True)
    (tmp_path / "repo" / "media").mkdir()
    outside = tmp_path / "secret.png"
    outside.write_bytes(b"png")
    settings.BASE_DIR = worktree
    settings.MEDIA_ROOT = str(worktree / "media")
    settings.MEDIA_URL = "/media/"

    assert to_media_url(str(outside)) == ""
    assert resolve_media_file("../secret.png") == ""

from pathlib import Path

from apps.code_monitor.screening import select_candidate_files


def _write(path: Path, text: str = "x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_skips_dependency_build_and_binary(tmp_path: Path):
    _write(tmp_path / "node_modules" / "lib" / "api.js", "axios.get('/skip')")
    _write(tmp_path / "venv" / "views.py", "urlpatterns = []")
    _write(tmp_path / ".venv" / "urls.py", "urlpatterns = []")
    _write(tmp_path / "dist" / "controller.js", "fetch('/skip')")
    _write(tmp_path / "build" / "router.js", "app.get('/skip')")
    _write(tmp_path / ".git" / "config", "api")
    _write(tmp_path / "pkg" / "__pycache__" / "views.py", "urlpatterns = []")
    _write(tmp_path / "package-lock.json", "axios")
    _write(tmp_path / "yarn.lock", "axios")
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\r\n")
    kept = select_candidate_files(tmp_path)
    assert kept == []


def test_keeps_path_or_content_match(tmp_path: Path):
    _write(tmp_path / "src" / "api" / "client.js", "export const x = 1")
    _write(tmp_path / "src" / "plain.js", "axios.get('/orders')")
    _write(tmp_path / "readme.txt", "this file has no interface")
    kept = [p.relative_to(tmp_path).as_posix() for p in select_candidate_files(tmp_path)]
    assert kept == ["src/api/client.js", "src/plain.js"]


def test_content_keywords(tmp_path: Path):
    samples = {
        "a.js": "fetch('/a')",
        "b.py": "urlpatterns = []",
        "c.java": "@GetMapping('/c')",
        "d.java": "@PostMapping('/d')",
        "e.java": "@PutMapping('/e')",
        "f.java": "@DeleteMapping('/f')",
        "g.java": "@PatchMapping('/g')",
        "h.js": "app.get('/h')",
        "i.js": "app.post('/i')",
        "j.js": "app.put('/j')",
        "k.js": "app.delete('/k')",
        "l.js": "router.get('/l')",
        "m.js": "router.post('/m')",
        "n.js": "router.put('/n')",
        "o.js": "router.delete('/o')",
    }
    for name, text in samples.items():
        _write(tmp_path / name, text)
    kept = {p.name for p in select_candidate_files(tmp_path)}
    assert kept == set(samples)

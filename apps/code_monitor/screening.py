from pathlib import Path

SKIP_DIR_NAMES = {
    ".git",
    "node_modules",
    "venv",
    ".venv",
    "dist",
    "build",
    "__pycache__",
}
LOCK_FILE_NAMES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "Pipfile.lock",
    "Cargo.lock",
    "composer.lock",
}
BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico",
    ".zip", ".tar", ".gz", ".7z", ".jar", ".war",
    ".pdf", ".mp4", ".mp3", ".woff", ".woff2", ".ttf", ".eot",
    ".exe", ".dll", ".so", ".pyc", ".class",
}
PATH_KEYWORDS = (
    "api", "router", "controller", "views", "urls", "serializer", "route",
)
CONTENT_KEYWORDS = (
    "axios", "fetch", "urlpatterns",
    "@GetMapping", "@PostMapping", "@PutMapping", "@DeleteMapping", "@PatchMapping",
    "app.get", "app.post", "app.put", "app.delete",
    "router.get", "router.post", "router.put", "router.delete",
)


def select_candidate_files(root: Path) -> list[Path]:
    kept = []
    for path in _walk(root):
        if _path_matches(path, root) or _content_matches(path):
            kept.append(path)
    return sorted(kept)


def _walk(root: Path):
    for dirpath, dirnames, filenames in os_walk(root):
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIR_NAMES]
        for filename in filenames:
            path = Path(dirpath) / filename
            if _skipped_file(path):
                continue
            yield path


def os_walk(root: Path):
    import os
    return os.walk(root)


def _skipped_file(path: Path) -> bool:
    name = path.name
    if name in LOCK_FILE_NAMES or name.endswith(".lock"):
        return True
    if path.suffix.lower() in BINARY_SUFFIXES:
        return True
    return False


def _path_matches(path: Path, root: Path) -> bool:
    relative = path.relative_to(root).as_posix().casefold()
    return any(keyword in relative for keyword in PATH_KEYWORDS)


def _content_matches(path: Path) -> bool:
    try:
        chunk = path.read_bytes()[:8192]
    except OSError:
        return False
    if b"\x00" in chunk:
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return any(keyword in text for keyword in CONTENT_KEYWORDS)

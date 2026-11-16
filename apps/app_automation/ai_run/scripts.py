# -*- coding: utf-8 -*-
"""List builtin fixtures and persist uploaded .feature files. Paths stay server-side."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from tools.req001.bdd_parser import parse_feature_file, parse_gherkin
from tools.req001.errors import ParseError
from tools.req001.paths import bdd_dir, repo_root

from .models import AiRunScript
from .storage import upload_path

BUILTIN_PREFIX = "builtin:"
UPLOAD_PREFIX = "upload:"


def _feature_display_name(feature) -> str:
    if feature.scenarios:
        first = feature.scenarios[0]
        if first.case_id and first.name:
            return f"{first.case_id} {first.name}"
        return first.name or first.case_id or feature.name
    return feature.name or "未命名脚本"


def list_builtin_scripts(root: Optional[Path] = None) -> List[dict]:
    directory = bdd_dir(root or repo_root())
    items: List[dict] = []
    if not directory.is_dir():
        return items
    for path in sorted(directory.glob("*.feature")):
        try:
            feature = parse_feature_file(path)
        except ParseError:
            continue
        script_id = f"{BUILTIN_PREFIX}{path.stem}"
        items.append(
            {
                "id": script_id,
                "name": _feature_display_name(feature),
                "source": "builtin",
                "scenario_count": len(feature.scenarios),
            }
        )
    return items


def list_uploaded_scripts(user) -> List[dict]:
    items = []
    for script in AiRunScript.objects.filter(user=user).order_by("-created_at"):
        items.append(
            {
                "id": f"{UPLOAD_PREFIX}{script.id}",
                "name": script.display_name or script.original_name,
                "source": "upload",
                "original_name": script.original_name,
            }
        )
    return items


def list_available_scripts(user, root: Optional[Path] = None) -> List[dict]:
    return list_builtin_scripts(root) + list_uploaded_scripts(user)


def save_uploaded_feature(user, original_name: str, content: str, root: Optional[Path] = None) -> AiRunScript:
    name = Path(original_name or "upload.feature").name
    if not name.lower().endswith(".feature"):
        from .constants import INVALID_UPLOAD

        raise ValueError(INVALID_UPLOAD)
    try:
        feature = parse_gherkin(content)
    except ParseError as exc:
        from .constants import INVALID_FEATURE

        message = str(exc).strip() or INVALID_FEATURE
        # Never include file paths from the parser.
        if "夹具" in message or "解析" in message or "为空" in message:
            raise ValueError(message) from exc
        raise ValueError(INVALID_FEATURE) from exc
    if not feature.scenarios:
        from .constants import INVALID_FEATURE

        raise ValueError(INVALID_FEATURE)

    script = AiRunScript(
        user=user,
        original_name=name,
        display_name=_feature_display_name(feature),
        relative_path="",
    )
    script.save()
    dest = upload_path(user.id, script.id, root)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding="utf-8")
    from .storage import relative_to_repo

    script.relative_path = relative_to_repo(dest, root)
    script.save(update_fields=["relative_path"])
    return script


def resolve_script_paths(user, script_ids: Sequence[str], root: Optional[Path] = None) -> Tuple[List[Path], List[str]]:
    """Map public script ids to existing files. Raises ValueError on unknown/illegal ids."""
    from .constants import SCRIPT_NOT_FOUND

    root = root or repo_root()
    paths: List[Path] = []
    normalized: List[str] = []
    if not script_ids:
        from .constants import NO_SCRIPTS_SELECTED

        raise ValueError(NO_SCRIPTS_SELECTED)

    for raw in script_ids:
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError(SCRIPT_NOT_FOUND)
        script_id = raw.strip()
        if script_id.startswith(BUILTIN_PREFIX):
            stem = script_id[len(BUILTIN_PREFIX):]
            if not stem or "/" in stem or "\\" in stem or ".." in stem:
                raise ValueError(SCRIPT_NOT_FOUND)
            path = bdd_dir(root) / f"{stem}.feature"
            if not path.is_file() or not _is_under(path, bdd_dir(root)):
                raise ValueError(SCRIPT_NOT_FOUND)
            paths.append(path)
            normalized.append(script_id)
        elif script_id.startswith(UPLOAD_PREFIX):
            token = script_id[len(UPLOAD_PREFIX):]
            try:
                script = AiRunScript.objects.get(id=token, user=user)
            except (AiRunScript.DoesNotExist, ValueError):
                raise ValueError(SCRIPT_NOT_FOUND)
            path = (root / script.relative_path).resolve() if script.relative_path else upload_path(user.id, script.id, root)
            if not path.is_file():
                raise ValueError(SCRIPT_NOT_FOUND)
            paths.append(path)
            normalized.append(script_id)
        else:
            raise ValueError(SCRIPT_NOT_FOUND)
    return paths, normalized


def _is_under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False

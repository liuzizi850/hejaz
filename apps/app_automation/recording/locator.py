# -*- coding: utf-8 -*-


def _center(bounds):
    if not isinstance(bounds, dict):
        return None
    try:
        return (
            float(bounds["x"]) + float(bounds["w"]) / 2.0,
            float(bounds["y"]) + float(bounds["h"]) / 2.0,
        )
    except (KeyError, TypeError, ValueError):
        return None


def _distance(left, right):
    a = _center(left)
    b = _center(right)
    if a is None or b is None:
        return 0.0
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def select_by_identity(step, nodes):
    """按 resource_id、content_desc、text+class_name 的顺序选一个节点。找不到返回 None。"""
    step = step or {}
    nodes = nodes or []
    resource_id = step.get("resource_id") or ""
    content_desc = step.get("content_desc") or ""
    text = step.get("text") or ""
    class_name = step.get("class_name") or ""

    if resource_id:
        matched = [node for node in nodes if (node.get("resource_id") or "") == resource_id]
    elif content_desc:
        matched = [node for node in nodes if (node.get("content_desc") or "") == content_desc]
    elif text and class_name:
        matched = [
            node for node in nodes
            if (node.get("text") or "") == text and (node.get("class_name") or "") == class_name
        ]
    else:
        return None

    if not matched:
        return None
    if len(matched) == 1:
        return matched[0]
    return min(matched, key=lambda node: _distance(step.get("bounds"), node.get("bounds")))

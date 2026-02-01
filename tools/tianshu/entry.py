import json
import os
import re


def _read_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def find_talents_dir(project_root: str | None = None) -> str | None:
    root = os.path.abspath(project_root) if project_root else os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    candidates = [
        os.path.join(root, "tools", "tianshu", "data", "talents"),
    ]
    for p in candidates:
        if os.path.isdir(p):
            return p
    return None


def list_tree_ids(talents_dir: str) -> list[str]:
    out: list[str] = []
    try:
        for name in os.listdir(talents_dir):
            if re.fullmatch(r"p\d+_s\d+\.json", name):
                out.append(os.path.splitext(name)[0])
    except Exception:
        return []
    out.sort()
    return out


def load_tree_nodes(talents_dir: str, tree_id: str) -> list[dict]:
    tree_id = str(tree_id or "").strip()
    if not tree_id:
        return []
    path = os.path.join(talents_dir, f"{tree_id}.json")
    raw = _read_json(path, [])
    if not isinstance(raw, list):
        return []
    return [x for x in raw if isinstance(x, dict)]

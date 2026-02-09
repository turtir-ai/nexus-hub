#!/usr/bin/env python3
"""Project scan utilities used to build/update mental model state.

Design goals:
- stdlib only
- deterministic-ish outputs (sorted where reasonable)
- safe defaults (ignore common large dirs)
"""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List


IGNORE_DIR_NAMES = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    "__pycache__",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".idea",
    ".vscode",
    ".terraform",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def find_project_root(start: Path) -> Path:
    """Walk up from start until we find a likely project root."""
    cur = start.expanduser().resolve()
    for _ in range(25):
        if (
            (cur / ".git").exists()
            or (cur / "pyproject.toml").exists()
            or (cur / "requirements.txt").exists()
            or (cur / "package.json").exists()
        ):
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return start.expanduser().resolve()


def _iter_files(root: Path, max_files: int = 100_000) -> Iterable[Path]:
    """Yield files under root, skipping ignored dirs."""
    count = 0
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        # Prune large/common dirs.
        dirnames[:] = sorted([d for d in dirnames if d not in IGNORE_DIR_NAMES])
        for fname in sorted(filenames):
            count += 1
            if count > max_files:
                return
            yield Path(dirpath) / fname


def _language_for_suffix(suffix: str) -> str:
    ext = suffix.lower()
    return {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".jsx": "javascript",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".kt": "kotlin",
        ".rb": "ruby",
        ".php": "php",
        ".cs": "csharp",
        ".c": "c",
        ".h": "c",
        ".cpp": "cpp",
        ".hpp": "cpp",
        ".m": "objective-c",
        ".mm": "objective-c++",
        ".swift": "swift",
        ".sh": "shell",
        ".bash": "shell",
        ".zsh": "shell",
        ".json": "json",
        ".toml": "toml",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".md": "markdown",
        ".html": "html",
        ".css": "css",
        ".sql": "sql",
        ".tf": "terraform",
        ".dockerfile": "docker",
        ".yaml.tmpl": "yaml",
    }.get(ext, "other")


def _read_text(path: Path, limit_bytes: int = 200_000) -> str:
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    if len(raw) > limit_bytes:
        raw = raw[:limit_bytes]
    try:
        return raw.decode("utf-8", errors="replace")
    except UnicodeDecodeError:
        return ""


def _parse_requirements(lines: List[str], max_items: int = 200) -> List[str]:
    deps: List[str] = []
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("-"):
            # Skip includes/options.
            continue
        deps.append(s)
        if len(deps) >= max_items:
            break
    return deps


def _python_dependency_hints(root: Path) -> Dict[str, Any]:
    hints: Dict[str, Any] = {"type": "python", "sources": []}

    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        try:
            import tomllib  # py>=3.11

            data = tomllib.loads(_read_text(pyproject))
        except Exception:
            data = {}

        deps: List[str] = []
        project = data.get("project") if isinstance(data, dict) else {}
        if isinstance(project, dict):
            deps.extend([str(x) for x in (project.get("dependencies") or []) if x is not None])
            optional = project.get("optional-dependencies")
            if isinstance(optional, dict):
                for _, items in optional.items():
                    if isinstance(items, list):
                        deps.extend([str(x) for x in items if x is not None])

        tool = data.get("tool") if isinstance(data, dict) else {}
        poetry = (tool.get("poetry") if isinstance(tool, dict) else None) or {}
        if isinstance(poetry, dict):
            poetry_deps = poetry.get("dependencies")
            if isinstance(poetry_deps, dict):
                deps.extend([str(k) for k in poetry_deps.keys() if k != "python"])

        unique = sorted({d.strip() for d in deps if str(d).strip()})
        hints["sources"].append(
            {
                "path": "pyproject.toml",
                "count": len(unique),
                "examples": unique[:25],
            }
        )

    req = root / "requirements.txt"
    if req.exists():
        deps = _parse_requirements(_read_text(req).splitlines())
        hints["sources"].append(
            {"path": "requirements.txt", "count": len(deps), "examples": deps[:25]}
        )

    return hints


def _node_dependency_hints(root: Path) -> Dict[str, Any]:
    pkg = root / "package.json"
    if not pkg.exists():
        return {"type": "node", "sources": []}
    try:
        data = json.loads(_read_text(pkg))
    except json.JSONDecodeError:
        data = {}

    def _keys(obj: Any) -> List[str]:
        if isinstance(obj, dict):
            return sorted([str(k) for k in obj.keys()])
        return []

    deps = _keys(data.get("dependencies"))
    dev = _keys(data.get("devDependencies"))
    return {
        "type": "node",
        "sources": [
            {
                "path": "package.json",
                "dependencies_count": len(deps),
                "dev_dependencies_count": len(dev),
                "examples": (deps + dev)[:25],
            }
        ],
    }


def scan_project(root: Path, max_files: int = 100_000) -> Dict[str, Any]:
    """Return a lightweight, evidence-friendly scan summary."""
    root = root.expanduser().resolve()

    suffix_counts: Counter[str] = Counter()
    lang_counts: Counter[str] = Counter()
    file_count = 0

    for path in _iter_files(root, max_files=max_files):
        if not path.is_file():
            continue
        file_count += 1
        suffix = path.suffix.lower()
        suffix_counts[suffix or "<noext>"] += 1
        lang_counts[_language_for_suffix(suffix)] += 1

    top_level_dirs = sorted(
        [
            p.name
            for p in root.iterdir()
            if p.is_dir() and p.name not in IGNORE_DIR_NAMES
        ]
    )

    is_python = (root / "pyproject.toml").exists() or (root / "requirements.txt").exists()
    is_node = (root / "package.json").exists()
    project_type = "mixed" if (is_python and is_node) else ("python" if is_python else ("node" if is_node else "unknown"))

    dep_hints: List[Dict[str, Any]] = []
    if is_python:
        dep_hints.append(_python_dependency_hints(root))
    if is_node:
        dep_hints.append(_node_dependency_hints(root))

    return {
        "scanned_at": _now_iso(),
        "root": str(root),
        "project_type": project_type,
        "file_count": file_count,
        "extensions": dict(suffix_counts.most_common(30)),
        "languages": dict(lang_counts.most_common(30)),
        "top_level_dirs": top_level_dirs[:30],
        "dependency_hints": dep_hints,
    }

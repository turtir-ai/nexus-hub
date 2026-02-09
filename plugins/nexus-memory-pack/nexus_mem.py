#!/usr/bin/env python3
"""
NEXUS Memory Tools (portable, low-bloat).

Design goals:
- Keep ~/.claude/memory_bank.md small (hot/prompt memory).
- Store long-term notes in ~/.claude/memory/notes.jsonl (cold memory).
- Rotate oversized memory_bank snapshots into ~/.claude/memory/archives/.
- Provide deterministic search across: memory_bank, archives, notes, state, memory_v2, and project memory.

This is intentionally stdlib-only and macOS-friendly.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


DEFAULT_MAX_BYTES = 40_000  # aligns with Claude Code warning threshold
DEFAULT_PINNED_MAX_BYTES = 8_000
DEFAULT_RECENT_NOTES = 12
DEFAULT_STDIN_MAX_BYTES = 5_000_000

SENSITIVE_SUBSTRINGS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "API_KEY",
    "AUTH_TOKEN",
    "Authorization:",
    "Bearer ",
    "sk-",
    "xai-",
    "AIza",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def json_dumps(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True)


def claude_dir_from_env() -> Optional[Path]:
    override = os.environ.get("NEXUS_CLAUDE_DIR", "").strip()
    if not override:
        return None
    return Path(os.path.expanduser(override)).resolve()


@dataclass(frozen=True)
class MemoryPaths:
    claude_dir: Path
    memory_bank: Path
    memory_dir: Path
    pinned: Path
    notes_jsonl: Path
    archives_dir: Path
    archives_index: Path


def get_paths(claude_dir: Optional[Path] = None) -> MemoryPaths:
    base = claude_dir or claude_dir_from_env() or (Path.home() / ".claude")
    base = base.expanduser().resolve()
    mem_dir = base / "memory"
    archives_dir = mem_dir / "archives"
    return MemoryPaths(
        claude_dir=base,
        memory_bank=base / "memory_bank.md",
        memory_dir=mem_dir,
        pinned=mem_dir / "pinned.md",
        notes_jsonl=mem_dir / "notes.jsonl",
        archives_dir=archives_dir,
        archives_index=archives_dir / "INDEX.md",
    )


def ensure_dirs(paths: MemoryPaths) -> None:
    paths.memory_dir.mkdir(parents=True, exist_ok=True)
    paths.archives_dir.mkdir(parents=True, exist_ok=True)
    if not paths.archives_index.exists():
        paths.archives_index.write_text(
            "# Memory Archives Index\n\n"
            "This directory contains rotated snapshots of `~/.claude/memory_bank.md`.\n\n"
            "## Entries\n\n",
            encoding="utf-8",
        )


def safe_truncate_text(text: str, max_bytes: int) -> str:
    b = text.encode("utf-8", errors="replace")
    if len(b) <= max_bytes:
        return text
    # Truncate on UTF-8 byte boundary, then trim to full line.
    truncated = b[:max_bytes].decode("utf-8", errors="ignore")
    if "\n" in truncated:
        truncated = truncated.rsplit("\n", 1)[0] + "\n"
    return truncated


def default_pinned_template() -> str:
    return (
        "# CLAUDE MEMORY BANK (persistent context)\n\n"
        f"Last updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n\n"
        "## User\n"
        "- Name: <your name>\n"
        "- Role: <your role>\n"
        "- Communication: direct, technical, evidence-first\n\n"
        "## Claude Code\n"
        "- Keep memory_bank SMALL. Put details into notes.jsonl / project memory / state.\n\n"
        "## NEXUS\n"
        "- State: `~/.claude/state/`\n"
        "- Tests: `python3 ~/.claude/tests/run_all.py`\n\n"
        "## Safety / scope\n"
        "- No secrets in memory (.env, keys, tokens)\n"
        "- No unauthorized access / payment bypass\n"
    )


def ensure_pinned(paths: MemoryPaths, pinned_max_bytes: int = DEFAULT_PINNED_MAX_BYTES) -> None:
    if paths.pinned.exists():
        return

    if paths.memory_bank.exists():
        src = paths.memory_bank.read_text(encoding="utf-8", errors="replace")
        content = safe_truncate_text(src, pinned_max_bytes)
        if not content.strip():
            content = default_pinned_template()
    else:
        content = default_pinned_template()

    paths.pinned.write_text(content.rstrip() + "\n", encoding="utf-8")


def iter_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict):
            yield obj


def append_jsonl(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def read_stdin_json(max_bytes: int = DEFAULT_STDIN_MAX_BYTES) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """
    Best-effort read + parse stdin JSON.
    Never raises; returns (event_or_none, meta).
    """
    meta: Dict[str, Any] = {"ok": True, "bytes": 0, "truncated": False}
    try:
        data = sys.stdin.buffer.read(max_bytes + 1)
    except Exception as e:
        meta.update({"ok": False, "error": f"stdin_read_failed:{type(e).__name__}", "detail": str(e)})
        return None, meta

    if not data:
        meta.update({"bytes": 0})
        return None, meta

    if len(data) > max_bytes:
        data = data[:max_bytes]
        meta["truncated"] = True

    meta["bytes"] = len(data)
    try:
        text = data.decode("utf-8", errors="replace")
        obj = json.loads(text)
    except Exception as e:
        meta.update({"ok": False, "error": f"stdin_json_parse_failed:{type(e).__name__}", "detail": str(e)})
        return None, meta

    if not isinstance(obj, dict):
        meta.update({"ok": False, "error": "stdin_json_not_object"})
        return None, meta

    return obj, meta


def redact_sensitive(text: str) -> str:
    # Fast path: avoid regex work for most strings.
    if not any(s in text for s in SENSITIVE_SUBSTRINGS):
        return text

    redacted = text
    # Authorization: Bearer <token>
    redacted = re.sub(r"(?i)(authorization:\s*bearer)\s+[^\s]+", r"\1 [REDACTED]", redacted)
    # KEY=VALUE style (best-effort)
    redacted = re.sub(r"(?i)\b([A-Z0-9_]*API[_-]?KEY|AUTH[_-]?TOKEN)\b\s*=\s*([^\s]+)", r"\1=[REDACTED]", redacted)
    # Bearer tokens in URLs/headers
    redacted = re.sub(r"(?i)\bbearer\s+[^\s]+", "Bearer [REDACTED]", redacted)
    # OpenAI-like tokens (sk-...)
    redacted = re.sub(r"\bsk-[A-Za-z0-9]{10,}\b", "sk-[REDACTED]", redacted)
    return redacted


def short_one_line(text: str, limit: int = 360) -> str:
    s = (text or "").strip().replace("\r", " ").replace("\n", " ")
    s = redact_sensitive(s)
    if len(s) <= limit:
        return s
    return s[: limit - 3] + "..."


def coerce_str(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, str):
        return x
    try:
        return json.dumps(x, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(x)


def extract_failure_info(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    tool_name = str(event.get("tool_name") or event.get("name") or "").strip()
    resp = event.get("tool_response")
    if isinstance(resp, dict):
        exit_code = resp.get("exit_code")
        success = resp.get("success")
        error = resp.get("error") or resp.get("exception")
        stderr = resp.get("stderr")
        stdout = resp.get("stdout")

        failed = False
        if isinstance(exit_code, int) and exit_code != 0:
            failed = True
        if isinstance(success, bool) and success is False:
            failed = True
        if error:
            failed = True

        if not failed:
            return None

        return {
            "tool_name": tool_name,
            "exit_code": exit_code if isinstance(exit_code, int) else None,
            "success": success if isinstance(success, bool) else None,
            "error": short_one_line(coerce_str(error), limit=220) if error else "",
            "stderr": short_one_line(stderr or "", limit=220),
            "stdout": short_one_line(stdout or "", limit=220),
        }

    # String response: best-effort heuristics.
    s = coerce_str(resp)
    if not s.strip():
        return None
    if any(tok in s for tok in ("Traceback (most recent call last)", "SyntaxError", "NameError", "ImportError", "Error:", "Exception")):
        return {"tool_name": tool_name, "exit_code": None, "success": None, "error": short_one_line(s, limit=220), "stderr": "", "stdout": ""}
    return None


def remember_from_hook(
    paths: MemoryPaths,
    event: Dict[str, Any],
    additional_tags: Sequence[str],
    scope: str,
    recent_notes: int,
    rebuild: bool,
) -> Dict[str, Any]:
    ensure_dirs(paths)
    ensure_pinned(paths)

    info = extract_failure_info(event)
    if not info:
        return {"ok": True, "action": "noop", "reason": "no_failure_detected", "timestamp": now_iso()}

    tool_name = info.get("tool_name") or "tool"
    cwd = str(event.get("cwd") or event.get("project_root") or Path.cwd())

    # Best-effort input summary without leaking secrets.
    tool_input = event.get("tool_input")
    if isinstance(tool_input, dict):
        for k in ("cmd", "command", "path", "file_path", "target", "args"):
            if k in tool_input:
                tool_input = {k: tool_input.get(k)}
                break
    input_summary = short_one_line(coerce_str(tool_input), limit=260)

    parts = [f"Tool {tool_name} failed in `{cwd}`."]
    if input_summary:
        parts.append(f"input={input_summary}")
    if info.get("exit_code") is not None:
        parts.append(f"exit_code={info['exit_code']}")
    if info.get("error"):
        parts.append(f"error={info['error']}")
    if info.get("stderr"):
        parts.append(f"stderr={info['stderr']}")

    text = " ".join(parts).strip()
    tags = ["tool_error", tool_name] + [t.strip().lstrip("#") for t in additional_tags if t and t.strip()]
    refs: List[str] = []

    note = {
        "id": hashlib.md5(f"tool_error:{tool_name}:{text}".encode("utf-8", errors="replace")).hexdigest()[:12],
        "ts": now_iso(),
        "category": "tool_error",
        "text": text,
        "tags": tags,
        "refs": refs,
        "scope": scope,
        "cwd": cwd,
        "meta": {
            "tool_name": tool_name,
            "exit_code": info.get("exit_code"),
            "success": info.get("success"),
        },
    }

    append_jsonl(paths.notes_jsonl, note)

    rebuilt = rebuild_memory_bank(paths, recent_notes=recent_notes) if rebuild else None
    return {
        "ok": True,
        "action": "remember-hook",
        "note": note,
        "rebuilt": rebuilt,
        "timestamp": now_iso(),
    }


def tar_safe_members(tf: tarfile.TarFile) -> List[tarfile.TarInfo]:
    safe: List[tarfile.TarInfo] = []
    for m in tf.getmembers():
        name = m.name
        if not name or name.startswith("/") or name.startswith("\\"):
            continue
        # Prevent path traversal
        if ".." in Path(name).parts:
            continue
        safe.append(m)
    return safe


def export_bundle(
    paths: MemoryPaths,
    out_path: Path,
    with_archives: bool,
    with_state: bool,
    recent_notes: int,
) -> Dict[str, Any]:
    ensure_dirs(paths)
    ensure_pinned(paths)
    rebuild_memory_bank(paths, recent_notes=recent_notes)

    out_path = out_path.expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    files: List[Path] = []
    for p in (paths.memory_bank, paths.pinned, paths.notes_jsonl, paths.archives_index):
        if p.exists() and p.is_file():
            files.append(p)

    if with_archives and paths.archives_dir.exists():
        snaps = sorted([p for p in paths.archives_dir.glob("memory_bank_*.md") if p.is_file()])
        files.extend(snaps)

    if with_state:
        state_dir = paths.claude_dir / "state"
        candidates = [
            "learning_patterns.json",
            "incidents.jsonl",
            "fix_queue.jsonl",
            "tasks.jsonl",
            "session_history.jsonl",
            "performance_metrics.json",
        ]
        for rel in candidates:
            p = state_dir / rel
            if p.exists() and p.is_file():
                files.append(p)

    # De-dup while preserving order
    uniq: List[Path] = []
    seen: set[str] = set()
    for p in files:
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    files = uniq

    manifest: Dict[str, Any] = {
        "ok": True,
        "kind": "nexus_mem_bundle",
        "created_at": now_iso(),
        "host": {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
        },
        "claude_dir": str(paths.claude_dir),
        "with_archives": with_archives,
        "with_state": with_state,
        "files": [],
    }

    # Build tar.gz with relative arcnames.
    try:
        with tarfile.open(out_path, "w:gz") as tf:
            for p in files:
                rel = p.relative_to(paths.claude_dir)
                tf.add(str(p), arcname=str(rel))
                manifest["files"].append(
                    {
                        "path": str(rel),
                        "bytes": p.stat().st_size,
                        "sha256": sha256_file(p),
                    }
                )

            # Manifest last
            mf_bytes = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
            ti = tarfile.TarInfo(name="MANIFEST.json")
            ti.size = len(mf_bytes)
            ti.mtime = int(datetime.now(timezone.utc).timestamp())
            tf.addfile(ti, fileobj=io.BytesIO(mf_bytes))  # type: ignore[name-defined]
    except Exception as e:
        return {"ok": False, "error": f"export_failed:{type(e).__name__}", "detail": str(e)}

    return {
        "ok": True,
        "action": "export",
        "bundle": str(out_path),
        "bundle_sha256": sha256_file(out_path),
        "files": manifest["files"],
        "timestamp": now_iso(),
    }


def import_bundle(
    paths: MemoryPaths,
    bundle_path: Path,
    overwrite_pinned: bool,
    recent_notes: int,
    rebuild: bool,
) -> Dict[str, Any]:
    ensure_dirs(paths)

    bundle_path = bundle_path.expanduser().resolve()
    if not bundle_path.exists():
        return {"ok": False, "error": "bundle_not_found", "bundle": str(bundle_path)}

    with tempfile.TemporaryDirectory(prefix="nexus_mem_import_") as td:
        tmp = Path(td)
        manifest: Optional[Dict[str, Any]] = None

        try:
            with tarfile.open(bundle_path, "r:gz") as tf:
                members = tar_safe_members(tf)
                # Read manifest if present.
                try:
                    mf = tf.extractfile("MANIFEST.json")
                except Exception:
                    mf = None
                if mf:
                    try:
                        manifest = json.loads(mf.read().decode("utf-8", errors="replace"))
                    except Exception:
                        manifest = None

                for m in members:
                    if m.name == "MANIFEST.json":
                        continue
                    tf.extract(m, path=tmp)
        except Exception as e:
            return {"ok": False, "error": f"import_failed:{type(e).__name__}", "detail": str(e)}

        imported: Dict[str, Any] = {"ok": True, "action": "import", "bundle": str(bundle_path), "timestamp": now_iso()}

        # Pinned
        src_pinned = tmp / "memory" / "pinned.md"
        if src_pinned.exists() and src_pinned.is_file():
            if overwrite_pinned or not paths.pinned.exists():
                paths.pinned.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_pinned, paths.pinned)
                imported["pinned"] = {"copied": True}
            else:
                imported["pinned"] = {"copied": False, "reason": "exists"}
        if not paths.pinned.exists():
            ensure_pinned(paths)

        # Notes (dedupe by id)
        src_notes = tmp / "memory" / "notes.jsonl"
        added = 0
        skipped = 0
        if src_notes.exists() and src_notes.is_file():
            existing_ids: set[str] = set()
            for n in iter_jsonl(paths.notes_jsonl):
                nid = str(n.get("id") or "")
                if nid:
                    existing_ids.add(nid)

            for n in iter_jsonl(src_notes):
                nid = str(n.get("id") or "")
                if not nid:
                    nid = hashlib.md5(f"{n.get('category','note')}:{n.get('text','')}".encode("utf-8", errors="replace")).hexdigest()[:12]
                    n["id"] = nid
                if nid in existing_ids:
                    skipped += 1
                    continue
                append_jsonl(paths.notes_jsonl, n)
                existing_ids.add(nid)
                added += 1

        imported["notes"] = {"added": added, "skipped": skipped}

        # Archives snapshots (optional in bundle)
        src_archives = tmp / "memory" / "archives"
        copied_archives = 0
        if src_archives.exists() and src_archives.is_dir():
            for fp in sorted(src_archives.glob("memory_bank_*.md")):
                if not fp.is_file():
                    continue
                dest = paths.archives_dir / fp.name
                if dest.exists():
                    # Avoid overwrite; keep both.
                    stem = dest.stem
                    suffix = dest.suffix
                    dest = paths.archives_dir / f"{stem}_imported{suffix}"
                shutil.copy2(fp, dest)
                copied_archives += 1
        if copied_archives:
            imported["archives"] = {"copied": copied_archives}

        # Restore archives index if provided (we keep local index and append imported one as a section).
        src_index = tmp / "memory" / "archives" / "INDEX.md"
        if src_index.exists() and src_index.is_file():
            try:
                imported_index = src_index.read_text(encoding="utf-8", errors="replace").strip()
            except Exception:
                imported_index = ""
            if imported_index:
                with paths.archives_index.open("a", encoding="utf-8") as f:
                    f.write("\n\n---\n\n")
                    f.write(f"_Imported from bundle: {bundle_path.name} at {now_iso()}_\n\n")
                    # Keep it compact: include only the Entries section if present.
                    if "## Entries" in imported_index:
                        f.write(imported_index.split("## Entries", 1)[-1].strip() + "\n")
                    else:
                        f.write(imported_index + "\n")

        if manifest is not None:
            imported["manifest"] = {"present": True}

        rebuilt = rebuild_memory_bank(paths, recent_notes=recent_notes) if rebuild else None
        imported["rebuilt"] = rebuilt
        return imported


def load_recent_notes(paths: MemoryPaths, limit: int) -> List[Dict[str, Any]]:
    notes = list(iter_jsonl(paths.notes_jsonl))
    return notes[-limit:]


def render_recent_notes_md(notes: Sequence[Dict[str, Any]]) -> str:
    if not notes:
        return "_No notes yet._\n"

    lines: List[str] = []
    for n in reversed(notes):
        ts = (n.get("ts") or "")[:10]
        cat = n.get("category") or "note"
        text = str(n.get("text") or "").strip().replace("\n", " ")
        if len(text) > 140:
            text = text[:137] + "..."
        tags = n.get("tags") or []
        tag_str = " ".join(f"#{t}" for t in tags if t)
        refs = n.get("refs") or []
        ref_str = ", ".join(str(r) for r in refs) if refs else ""

        suffix_parts = []
        if tag_str:
            suffix_parts.append(tag_str)
        if ref_str:
            suffix_parts.append(f"refs: {ref_str}")

        suffix = f" ({' | '.join(suffix_parts)})" if suffix_parts else ""
        lines.append(f"- [{ts}] **{cat}**: {text}{suffix}")

    return "\n".join(lines) + "\n"


def rebuild_memory_bank(paths: MemoryPaths, recent_notes: int = DEFAULT_RECENT_NOTES) -> Dict[str, Any]:
    ensure_dirs(paths)
    ensure_pinned(paths)

    pinned = paths.pinned.read_text(encoding="utf-8", errors="replace").rstrip()
    notes = load_recent_notes(paths, recent_notes)

    body = []
    body.append(pinned)
    body.append("")
    body.append("## Recent Notes (auto)\n")
    body.append(render_recent_notes_md(notes).rstrip())
    body.append("")
    body.append("## Memory Storage\n")
    body.append(f"- Notes (append-only): `{paths.notes_jsonl}`")
    body.append(f"- Archives index: `{paths.archives_index}`")
    body.append(f"- Archives dir: `{paths.archives_dir}`")
    body.append("")
    body.append(f"_Generated: {now_iso()}_")
    body.append("")

    out = "\n".join(body)
    paths.memory_bank.write_text(out, encoding="utf-8")

    return {
        "ok": True,
        "action": "rebuild",
        "memory_bank": str(paths.memory_bank),
        "pinned": str(paths.pinned),
        "notes_jsonl": str(paths.notes_jsonl),
        "archives_index": str(paths.archives_index),
        "recent_notes": len(notes),
        "timestamp": now_iso(),
    }


def rotate_memory_bank(
    paths: MemoryPaths,
    max_bytes: int = DEFAULT_MAX_BYTES,
    pinned_max_bytes: int = DEFAULT_PINNED_MAX_BYTES,
    recent_notes: int = DEFAULT_RECENT_NOTES,
    force: bool = False,
) -> Dict[str, Any]:
    ensure_dirs(paths)

    if not paths.memory_bank.exists():
        # Still ensure pinned exists for future sessions.
        ensure_pinned(paths, pinned_max_bytes=pinned_max_bytes)
        return {
            "ok": True,
            "action": "noop",
            "reason": "memory_bank_missing",
            "memory_bank": str(paths.memory_bank),
            "timestamp": now_iso(),
        }

    size = paths.memory_bank.stat().st_size
    if not force and size <= max_bytes:
        # Keep memory_bank fresh (ensures Recent Notes is present)
        return rebuild_memory_bank(paths, recent_notes=recent_notes)

    # Archive snapshot
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    archive_path = paths.archives_dir / f"memory_bank_{ts}.md"
    data = paths.memory_bank.read_bytes()

    archive_path.write_bytes(data)

    entry = {
        "archived_at": now_iso(),
        "file": archive_path.name,
        "bytes": len(data),
        "sha256": sha256_bytes(data),
        "reason": "force" if force else f"exceeded_max_bytes:{max_bytes}",
    }

    # Append to index
    with paths.archives_index.open("a", encoding="utf-8") as f:
        f.write(f"\n## {archive_path.name}\n")
        f.write(f"- Archived at: {entry['archived_at']}\n")
        f.write(f"- Bytes: {entry['bytes']}\n")
        f.write(f"- SHA256: {entry['sha256']}\n")
        f.write(f"- Reason: {entry['reason']}\n")

    # Ensure pinned exists (create from old bank if not already pinned)
    if not paths.pinned.exists():
        content = safe_truncate_text(data.decode("utf-8", errors="replace"), pinned_max_bytes)
        paths.pinned.write_text(content.rstrip() + "\n", encoding="utf-8")

    rebuilt = rebuild_memory_bank(paths, recent_notes=recent_notes)
    return {
        "ok": True,
        "action": "rotate",
        "archived": entry,
        "rebuilt": rebuilt,
        "timestamp": now_iso(),
    }


def remember_note(
    paths: MemoryPaths,
    category: str,
    text: str,
    tags: Sequence[str],
    refs: Sequence[str],
    scope: str,
    recent_notes: int = DEFAULT_RECENT_NOTES,
) -> Dict[str, Any]:
    ensure_dirs(paths)
    ensure_pinned(paths)

    clean_tags = [t.strip().lstrip("#") for t in tags if t and t.strip()]
    clean_refs = [r.strip() for r in refs if r and r.strip()]

    note = {
        "id": hashlib.md5(f"{category}:{text}".encode("utf-8", errors="replace")).hexdigest()[:12],
        "ts": now_iso(),
        "category": category,
        "text": text.strip(),
        "tags": clean_tags,
        "refs": clean_refs,
        "scope": scope,
        "cwd": str(Path.cwd()),
    }

    append_jsonl(paths.notes_jsonl, note)

    # Optional: also write detailed note into project memory.
    if scope == "project":
        proj_mem_dir = Path.cwd() / ".claude" / "memory"
        proj_mem_dir.mkdir(parents=True, exist_ok=True)
        proj_file = proj_mem_dir / "MEMORY.md"
        with proj_file.open("a", encoding="utf-8") as f:
            f.write(f"\n### {category} ({note['ts'][:10]})\n")
            if clean_tags:
                f.write(f"- Tags: {' '.join('#'+t for t in clean_tags)}\n")
            if clean_refs:
                f.write(f"- Refs: {', '.join(clean_refs)}\n")
            f.write(f"\n{note['text']}\n\n---\n")

    rebuilt = rebuild_memory_bank(paths, recent_notes=recent_notes)
    return {
        "ok": True,
        "action": "remember",
        "note": note,
        "rebuilt": rebuilt,
        "timestamp": now_iso(),
    }


def gather_search_paths(paths: MemoryPaths, include_state: bool, include_v2: bool, include_project: bool) -> List[Path]:
    search_paths: List[Path] = []

    for p in [paths.memory_bank, paths.pinned, paths.notes_jsonl, paths.archives_dir, paths.archives_index]:
        if p.exists():
            search_paths.append(p)

    # Historical memory_bank backups (created by prior tooling / manual snapshots).
    backups_dir = paths.claude_dir / "backups"
    if backups_dir.exists():
        for p in sorted(backups_dir.glob("memory_bank.md.backup_*")):
            if p.is_file():
                search_paths.append(p)

    if include_state:
        state_dir = paths.claude_dir / "state"
        candidates = [
            "learning_patterns.json",
            "incidents.jsonl",
            "fix_queue.jsonl",
            "tasks.jsonl",
            "session_history.jsonl",
            "performance_metrics.json",
        ]
        for rel in candidates:
            p = state_dir / rel
            if p.exists():
                search_paths.append(p)

    if include_v2:
        v2_dir = paths.claude_dir / "memory_v2"
        if v2_dir.exists():
            for p in sorted(v2_dir.glob("*.json")):
                search_paths.append(p)

    if include_project:
        proj_dir = Path.cwd() / ".claude" / "memory"
        if proj_dir.exists():
            search_paths.append(proj_dir)

    # De-dup while preserving order
    uniq: List[Path] = []
    seen: set[str] = set()
    for p in search_paths:
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    return uniq


def search(query: str, paths: List[Path], max_results: int = 120, use_rg: bool = True) -> Dict[str, Any]:
    query = query.strip()
    if not query:
        return {"ok": False, "error": "empty_query"}

    rg = shutil.which("rg") if use_rg else None
    results: List[Dict[str, Any]] = []

    if rg:
        cmd = [rg, "-n", "-S", "--no-heading", "--color=never", query]
        for p in paths:
            cmd.append(str(p))
        try:
            cp = subprocess.run(cmd, text=True, capture_output=True)
        except Exception as e:
            return {"ok": False, "error": f"rg_failed:{e}"}

        out = cp.stdout.splitlines()
        for line in out[:max_results]:
            # rg format: path:line:match
            parts = line.split(":", 2)
            if len(parts) == 3:
                file_path, line_no, match = parts
                results.append({"file": file_path, "line": int(line_no), "match": match})
            else:
                results.append({"raw": line})

        return {
            "ok": True,
            "engine": "rg",
            "query": query,
            "paths": [str(p) for p in paths],
            "matches": results,
            "truncated": len(out) > max_results,
        }

    # Fallback: naive scan (fast enough for our constrained file set)
    q = query.casefold()
    for p in paths:
        if len(results) >= max_results:
            break
        if p.is_dir():
            files = [x for x in p.rglob("*") if x.is_file() and x.stat().st_size <= 2_000_000]
        else:
            files = [p]
        for fp in files:
            if len(results) >= max_results:
                break
            try:
                lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
            except Exception:
                continue
            for i, line in enumerate(lines, 1):
                if q in line.casefold():
                    results.append({"file": str(fp), "line": i, "match": line.strip()})
                    if len(results) >= max_results:
                        break

    return {
        "ok": True,
        "engine": "python",
        "query": query,
        "paths": [str(p) for p in paths],
        "matches": results,
        "truncated": False,
    }


def cmd_stats(paths: MemoryPaths) -> Dict[str, Any]:
    ensure_dirs(paths)
    ensure_pinned(paths)

    def stat(p: Path) -> Dict[str, Any]:
        if not p.exists():
            return {"exists": False}
        if p.is_dir():
            files = [x for x in p.glob("**/*") if x.is_file()]
            total = sum(x.stat().st_size for x in files)
            return {"exists": True, "type": "dir", "files": len(files), "bytes": total}
        return {"exists": True, "type": "file", "bytes": p.stat().st_size, "sha256": sha256_file(p)}

    return {
        "ok": True,
        "timestamp": now_iso(),
        "claude_dir": str(paths.claude_dir),
        "memory_bank": stat(paths.memory_bank),
        "pinned": stat(paths.pinned),
        "notes": stat(paths.notes_jsonl),
        "archives": stat(paths.archives_dir),
        "archives_index": stat(paths.archives_index),
    }


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="nexus_mem", description="NEXUS memory tools (compact + searchable)")
    ap.add_argument("--claude-dir", default="", help="Override Claude dir (default: ~/.claude or $NEXUS_CLAUDE_DIR)")

    sub = ap.add_subparsers(dest="cmd", required=True)

    p_stats = sub.add_parser("stats", help="Show memory stats")
    p_stats.set_defaults(_fn="stats")

    p_rebuild = sub.add_parser("rebuild", help="Rebuild memory_bank from pinned + notes")
    p_rebuild.add_argument("--recent", type=int, default=DEFAULT_RECENT_NOTES)
    p_rebuild.set_defaults(_fn="rebuild")

    p_rotate = sub.add_parser("rotate", help="Rotate oversized memory_bank into archives; rebuild afterwards")
    p_rotate.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    p_rotate.add_argument("--pinned-max-bytes", type=int, default=DEFAULT_PINNED_MAX_BYTES)
    p_rotate.add_argument("--recent", type=int, default=DEFAULT_RECENT_NOTES)
    p_rotate.add_argument("--force", action="store_true")
    p_rotate.set_defaults(_fn="rotate")

    p_rem = sub.add_parser("remember", help="Append a note to notes.jsonl (and optionally project memory)")
    p_rem.add_argument("--category", default="learning")
    p_rem.add_argument("--tags", default="", help="Comma-separated tags (no #)")
    p_rem.add_argument("--refs", default="", help="Comma-separated file refs")
    p_rem.add_argument("--scope", choices=["global", "project"], default="global")
    p_rem.add_argument("--recent", type=int, default=DEFAULT_RECENT_NOTES)
    p_rem.add_argument("text", nargs=argparse.REMAINDER, help="Note text (quote it)")
    p_rem.set_defaults(_fn="remember")

    p_search = sub.add_parser("search", help="Search memory + state + project memory")
    p_search.add_argument("--max-results", type=int, default=120)
    p_search.add_argument("--no-rg", action="store_true")
    p_search.add_argument("--no-state", action="store_true")
    p_search.add_argument("--no-v2", action="store_true")
    p_search.add_argument("--no-project", action="store_true")
    p_search.add_argument("query", nargs=argparse.REMAINDER)
    p_search.set_defaults(_fn="search")

    p_hook = sub.add_parser(
        "remember-hook",
        help="Read a Claude Code hook event JSON from stdin and append an error note if the tool failed",
    )
    p_hook.add_argument("--tags", default="", help="Comma-separated additional tags")
    p_hook.add_argument("--scope", choices=["global", "project"], default="global")
    p_hook.add_argument("--recent", type=int, default=DEFAULT_RECENT_NOTES)
    p_hook.add_argument("--no-rebuild", action="store_true", help="Append note only; skip rebuilding memory_bank")
    p_hook.set_defaults(_fn="remember_hook")

    p_export = sub.add_parser("export", help="Export memory bundle (tar.gz) for moving to another machine")
    p_export.add_argument("--out", default="", help="Output bundle path (default: ~/.claude/memory/exports/...)")
    p_export.add_argument("--with-archives", action="store_true", help="Include archive snapshots (memory_bank_*.md)")
    p_export.add_argument("--with-state", action="store_true", help="Include selected ~/.claude/state files")
    p_export.add_argument("--recent", type=int, default=DEFAULT_RECENT_NOTES, help="Recent notes count used for rebuild")
    p_export.set_defaults(_fn="export")

    p_import = sub.add_parser("import", help="Import memory bundle (tar.gz) into current Claude dir")
    p_import.add_argument("--overwrite-pinned", action="store_true", help="Overwrite existing pinned.md")
    p_import.add_argument("--recent", type=int, default=DEFAULT_RECENT_NOTES)
    p_import.add_argument("--no-rebuild", action="store_true", help="Import only; skip rebuilding memory_bank")
    p_import.add_argument("bundle", help="Path to a bundle created by `nexus_mem export`")
    p_import.set_defaults(_fn="import")

    return ap.parse_args(list(argv))


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    claude_dir = Path(args.claude_dir).expanduser().resolve() if args.claude_dir else None
    paths = get_paths(claude_dir=claude_dir)

    try:
        if args._fn == "stats":
            out = cmd_stats(paths)
            print(json_dumps(out))
            return 0

        if args._fn == "rebuild":
            out = rebuild_memory_bank(paths, recent_notes=int(args.recent))
            print(json_dumps(out))
            return 0

        if args._fn == "rotate":
            out = rotate_memory_bank(
                paths,
                max_bytes=int(args.max_bytes),
                pinned_max_bytes=int(args.pinned_max_bytes),
                recent_notes=int(args.recent),
                force=bool(args.force),
            )
            print(json_dumps(out))
            return 0

        if args._fn == "remember":
            text = " ".join(args.text).strip()
            if not text:
                print(json_dumps({"ok": False, "error": "empty_text"}))
                return 2
            tags = [t for t in (args.tags.split(",") if args.tags else []) if t.strip()]
            refs = [r for r in (args.refs.split(",") if args.refs else []) if r.strip()]
            out = remember_note(
                paths,
                category=str(args.category),
                text=text,
                tags=tags,
                refs=refs,
                scope=str(args.scope),
                recent_notes=int(args.recent),
            )
            print(json_dumps(out))
            return 0

        if args._fn == "search":
            q = " ".join(args.query).strip()
            s_paths = gather_search_paths(
                paths,
                include_state=not bool(args.no_state),
                include_v2=not bool(args.no_v2),
                include_project=not bool(args.no_project),
            )
            out = search(q, s_paths, max_results=int(args.max_results), use_rg=not bool(args.no_rg))
            print(json_dumps(out))
            return 0 if out.get("ok") else 2

        if args._fn == "remember_hook":
            event, meta = read_stdin_json()
            tags = [t for t in (args.tags.split(",") if args.tags else []) if t.strip()]
            if not event:
                out = {
                    "ok": True,
                    "action": "noop",
                    "reason": meta.get("error") or "empty_stdin",
                    "stdin_meta": meta,
                    "timestamp": now_iso(),
                }
                print(json_dumps(out))
                return 0
            out = remember_from_hook(
                paths,
                event=event,
                additional_tags=tags,
                scope=str(args.scope),
                recent_notes=int(args.recent),
                rebuild=not bool(args.no_rebuild),
            )
            out["stdin_meta"] = meta
            print(json_dumps(out))
            return 0

        if args._fn == "export":
            out_arg = str(args.out or "").strip()
            if out_arg:
                out_path = Path(out_arg)
            else:
                ensure_dirs(paths)
                exports_dir = paths.memory_dir / "exports"
                ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                out_path = exports_dir / f"nexus_memory_{ts}.tar.gz"
            out = export_bundle(
                paths,
                out_path=out_path,
                with_archives=bool(args.with_archives),
                with_state=bool(args.with_state),
                recent_notes=int(args.recent),
            )
            print(json_dumps(out))
            return 0 if out.get("ok") else 2

        if args._fn == "import":
            out = import_bundle(
                paths,
                bundle_path=Path(str(args.bundle)),
                overwrite_pinned=bool(args.overwrite_pinned),
                recent_notes=int(args.recent),
                rebuild=not bool(args.no_rebuild),
            )
            print(json_dumps(out))
            return 0 if out.get("ok") else 2

        print(json_dumps({"ok": False, "error": f"unknown_cmd:{args._fn}"}))
        return 2
    except Exception as e:
        print(json_dumps({"ok": False, "error": f"exception:{type(e).__name__}", "detail": str(e)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

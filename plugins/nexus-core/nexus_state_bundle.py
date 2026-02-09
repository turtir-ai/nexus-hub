#!/usr/bin/env python3
"""
NEXUS state bundler for cross-machine portability.

This intentionally exports ONLY a safe allowlist of state files under ~/.claude/state.
It does not export API keys, settings.json, full chat history, or logs by default.

Commands:
  export  -> writes a .tar.gz bundle + manifest
  import  -> restores state from a bundle (default: replace)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import tarfile
import tempfile
from datetime import datetime, timezone
from typing import Dict, List, Tuple


STATE_ALLOWLIST = [
    "performance_metrics.json",
    "learning_patterns.json",
    "incidents.jsonl",
    "fix_queue.jsonl",
    "tasks.jsonl",
    "mental_model.json",
    "agent_messages.jsonl",
    "msv.json",
    "quality_report.json",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def claude_state_dir() -> pathlib.Path:
    return pathlib.Path.home() / ".claude" / "state"


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def build_manifest(state_dir: pathlib.Path, files: List[str]) -> Dict:
    manifest = {
        "created_at": now_iso(),
        "state_dir": str(state_dir),
        "files": [],
    }
    for rel in files:
        p = state_dir / rel
        if not p.exists() or not p.is_file():
            continue
        manifest["files"].append(
            {
                "path": rel,
                "bytes": p.stat().st_size,
                "sha256": sha256_file(p),
            }
        )
    return manifest


def export_bundle(out_path: pathlib.Path) -> Tuple[pathlib.Path, Dict]:
    state_dir = claude_state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)

    manifest = build_manifest(state_dir, STATE_ALLOWLIST)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(out_path, "w:gz") as tf:
        # Write manifest as a virtual file inside the tar.
        manifest_bytes = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")
        ti = tarfile.TarInfo(name="manifest.json")
        ti.size = len(manifest_bytes)
        ti.mtime = int(datetime.now(timezone.utc).timestamp())
        tf.addfile(ti, fileobj=_BytesReader(manifest_bytes))

        for item in manifest["files"]:
            rel = item["path"]
            tf.add(state_dir / rel, arcname=f"state/{rel}")

    return out_path, manifest


def import_bundle(bundle_path: pathlib.Path, mode: str) -> Dict:
    if mode not in {"replace"}:
        raise ValueError("Only --mode replace is supported in this MVP")

    state_dir = claude_state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="nexus_state_import_") as tmp:
        tmp_dir = pathlib.Path(tmp)
        with tarfile.open(bundle_path, "r:gz") as tf:
            tf.extractall(tmp_dir)

        manifest_path = tmp_dir / "manifest.json"
        if not manifest_path.exists():
            raise ValueError("Bundle missing manifest.json")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        restored = []
        skipped = []

        for item in manifest.get("files", []):
            rel = item.get("path")
            if not rel:
                continue
            src = tmp_dir / "state" / rel
            dst = state_dir / rel

            if not src.exists():
                skipped.append({"path": rel, "reason": "missing_in_bundle"})
                continue

            # Integrity check
            actual = sha256_file(src)
            expected = item.get("sha256")
            if expected and actual != expected:
                skipped.append({"path": rel, "reason": "sha256_mismatch"})
                continue

            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())
            restored.append({"path": rel, "bytes": dst.stat().st_size})

    return {
        "ok": True,
        "mode": mode,
        "bundle": str(bundle_path),
        "restored": restored,
        "skipped": skipped,
        "state_dir": str(state_dir),
        "timestamp": now_iso(),
    }


class _BytesReader:
    def __init__(self, data: bytes):
        self._data = data
        self._pos = 0

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self._data) - self._pos
        chunk = self._data[self._pos : self._pos + size]
        self._pos += len(chunk)
        return chunk


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="nexus_state_bundle", description="Export/import safe NEXUS state bundles")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_exp = sub.add_parser("export", help="Export a tar.gz bundle from ~/.claude/state")
    p_exp.add_argument(
        "--out",
        default="",
        help="Output path. Default: ~/.claude/state/exports/nexus_state_YYYYMMDD_HHMMSS.tar.gz",
    )

    p_imp = sub.add_parser("import", help="Import a tar.gz bundle into ~/.claude/state (replace mode)")
    p_imp.add_argument("bundle", help="Path to a previously exported .tar.gz bundle")
    p_imp.add_argument("--mode", default="replace", choices=["replace"])

    return ap.parse_args()


def main() -> int:
    args = parse_args()
    if args.cmd == "export":
        out = args.out
        if not out:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            out = str(claude_state_dir() / "exports" / f"nexus_state_{ts}.tar.gz")
        out_path = pathlib.Path(os.path.expanduser(out)).resolve()
        bundle, manifest = export_bundle(out_path)
        print(json.dumps({"ok": True, "bundle": str(bundle), "manifest": manifest}, indent=2, ensure_ascii=False))
        return 0

    if args.cmd == "import":
        result = import_bundle(pathlib.Path(args.bundle).expanduser().resolve(), mode=args.mode)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    raise ValueError(f"Unknown command: {args.cmd}")


if __name__ == "__main__":
    raise SystemExit(main())


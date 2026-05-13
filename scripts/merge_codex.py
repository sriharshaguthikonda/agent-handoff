#!/usr/bin/env python3
"""Merge agent-handoff hooks into Codex hooks.json.

Default target: ~/.codex/hooks.json (global).
Never overwrites — appends only missing entries. Backs up first.

Usage:
    python scripts/merge_codex.py                     # global ~/.codex/hooks.json
    python scripts/merge_codex.py --target /path/to/hooks.json
    python scripts/merge_codex.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent


def _codex_hooks() -> dict:
    repo_posix = _REPO.as_posix()
    return {
        "Stop": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": f"python {repo_posix}/codex/stop_gate.py",
                        "timeout": 30,
                    }
                ]
            }
        ],
        "SessionStart": [
            {
                "matcher": "startup|resume",
                "hooks": [
                    {
                        "type": "command",
                        "command": f"python {repo_posix}/codex/session_start.py",
                        "timeout": 10,
                    }
                ]
            }
        ],
    }


def _existing_commands(entries: list[dict]) -> set[str]:
    cmds: set[str] = set()
    for entry in entries:
        for h in entry.get("hooks", []):
            cmd = h.get("command", "")
            if cmd:
                cmds.add(cmd)
    return cmds


def merge_hooks(existing: dict, additions: dict) -> tuple[dict, list[str]]:
    result: dict = dict(existing)
    added: list[str] = []
    for event, new_entries in additions.items():
        if event not in result:
            result[event] = list(new_entries)
            for entry in new_entries:
                for h in entry.get("hooks", []):
                    added.append(f"{event}/{h.get('command', '?')}")
        else:
            existing_cmds = _existing_commands(result[event])
            for entry in new_entries:
                entry_cmds = {h.get("command", "") for h in entry.get("hooks", [])}
                if not entry_cmds.intersection(existing_cmds):
                    result[event].append(entry)
                    for cmd in entry_cmds:
                        added.append(f"{event}/{cmd}")
    return result, added


def merge_into(settings_path: Path, dry_run: bool = False) -> int:
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    if settings_path.exists():
        try:
            current = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"warning: {settings_path} invalid JSON, treating as empty", file=sys.stderr)
            current = {}
    else:
        current = {}

    current.setdefault("hooks", {})
    merged_hooks, added = merge_hooks(current["hooks"], _codex_hooks())
    current["hooks"] = merged_hooks

    if not added:
        print(f"nothing to add - hooks already present in {settings_path}")
        return 0

    if dry_run:
        print(f"[dry-run] would write {settings_path}:")
        print(json.dumps(current, indent=2))
        print(f"\nwould add: {added}")
        return 0

    if settings_path.exists():
        bak = settings_path.with_suffix(".json.bak")
        shutil.copy2(str(settings_path), str(bak))
        print(f"backed up -> {bak}")

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".tmp", dir=settings_path.parent, delete=False, encoding="utf-8"
    ) as f:
        json.dump(current, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
        tmp = f.name
    os.replace(tmp, str(settings_path))

    print(f"merged -> {settings_path}")
    for item in added:
        print(f"  + {item}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Merge agent-handoff hooks into Codex hooks.json")
    ap.add_argument("--target", help="Explicit hooks.json path (default: ~/.codex/hooks.json)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.target:
        settings_path = Path(args.target)
    else:
        settings_path = Path.home() / ".codex" / "hooks.json"

    return merge_into(settings_path, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())

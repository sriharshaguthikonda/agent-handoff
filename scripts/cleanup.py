#!/usr/bin/env python3
"""Phase 7: Retention and cleanup for agent-handoff runtime files.

Archives or purges old question/answer pairs.

Usage:
    python scripts/cleanup.py --dry-run          # show what would be archived
    python scripts/cleanup.py --archive          # move old pairs to archive/YYYY-MM/
    python scripts/cleanup.py --purge            # hard-delete old pairs (irreversible)
    python scripts/cleanup.py --status           # disk usage + pending/answered counts
    python scripts/cleanup.py --max-mb 50        # abort archive/purge if total > 50 MB

Retention window: HANDOFF_RETENTION_DAYS env var (default 30).
A pair is eligible when its question's created_at is older than the retention window
AND the answer has been consumed (q_*.consumed.json exists).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from lib.core import HANDOFF_ROOT, load_env


def _dir_mb(path: Path) -> float:
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return total / (1024 * 1024)


def _question_age_days(qpath: Path) -> float | None:
    try:
        obj = json.loads(qpath.read_text(encoding="utf-8"))
        created_at = obj.get("created_at", "")
        if not created_at:
            return None
        created = datetime.fromisoformat(created_at)
        return (datetime.now(timezone.utc) - created).total_seconds() / 86400
    except Exception:
        return None


def _eligible_pairs(root: Path, retention_days: int) -> list[tuple[Path, Path | None]]:
    """Return list of (question_path, consumed_answer_path | None) ready for cleanup."""
    questions_dir = root / "questions"
    answers_dir = root / "answers"
    pairs: list[tuple[Path, Path | None]] = []

    for qpath in sorted(questions_dir.glob("q_*.json")):
        age = _question_age_days(qpath)
        if age is None or age < retention_days:
            continue
        qid = qpath.stem  # q_<id>
        consumed = answers_dir / f"{qid}.consumed.json"
        if consumed.exists():
            pairs.append((qpath, consumed))
        # unconsumed old questions (no answer ever written) also eligible
        elif not (answers_dir / f"{qid}.json").exists():
            pairs.append((qpath, None))
    return pairs


def cmd_status(root: Path, env: dict) -> int:
    questions_dir = root / "questions"
    answers_dir = root / "answers"
    audit_path = root / "audit" / "events.jsonl"
    archive_dir = root / "archive"

    pending = len(list(questions_dir.glob("q_*.json")))
    consumed = len(list(answers_dir.glob("q_*.consumed.json")))
    waiting = len(list(answers_dir.glob("q_*.json")))

    print(f"questions/  : {pending} files  ({_dir_mb(questions_dir):.2f} MB)")
    print(f"answers/    : {waiting} waiting, {consumed} consumed  ({_dir_mb(answers_dir):.2f} MB)")
    if audit_path.exists():
        audit_lines = len(audit_path.read_text(encoding="utf-8").splitlines())
        print(f"audit/      : {audit_lines} events  ({audit_path.stat().st_size / 1024:.1f} KB)")
    if archive_dir.exists():
        print(f"archive/    : {_dir_mb(archive_dir):.2f} MB")

    retention_days = int(env.get("HANDOFF_RETENTION_DAYS", "30"))
    pairs = _eligible_pairs(root, retention_days)
    print(f"\n{len(pairs)} pairs eligible for cleanup (older than {retention_days}d + consumed)")
    return 0


def cmd_archive(root: Path, env: dict, dry_run: bool = False, max_mb: float | None = None) -> int:
    retention_days = int(env.get("HANDOFF_RETENTION_DAYS", "30"))
    pairs = _eligible_pairs(root, retention_days)
    if not pairs:
        print("nothing to archive")
        return 0

    if max_mb is not None:
        total = _dir_mb(root / "questions") + _dir_mb(root / "answers")
        if total > max_mb:
            print(f"abort: total runtime data {total:.1f} MB > --max-mb {max_mb}", file=sys.stderr)
            return 1

    moved = 0
    for qpath, apath in pairs:
        # archive bucket: archive/YYYY-MM/
        try:
            obj = json.loads(qpath.read_text(encoding="utf-8"))
            ts = obj.get("created_at", "")
            month = ts[:7] if ts else "unknown"
        except Exception:
            month = "unknown"

        dest_dir = root / "archive" / month
        if not dry_run:
            dest_dir.mkdir(parents=True, exist_ok=True)

        for src in [qpath, apath]:
            if src is None:
                continue
            dest = dest_dir / src.name
            if dry_run:
                print(f"[dry-run] archive {src.relative_to(root)} → {dest.relative_to(root)}")
            else:
                shutil.move(str(src), str(dest))
                print(f"archived {src.relative_to(root)} -> {dest.relative_to(root)}")
        moved += 1

    if not dry_run:
        print(f"archived {moved} pair(s)")
    return 0


def cmd_purge(root: Path, env: dict, dry_run: bool = False) -> int:
    retention_days = int(env.get("HANDOFF_RETENTION_DAYS", "30"))
    pairs = _eligible_pairs(root, retention_days)
    if not pairs:
        print("nothing to purge")
        return 0

    deleted = 0
    for qpath, apath in pairs:
        for src in [qpath, apath]:
            if src is None:
                continue
            if dry_run:
                print(f"[dry-run] delete {src.relative_to(root)}")
            else:
                src.unlink(missing_ok=True)
                print(f"deleted {src.relative_to(root)}")
        deleted += 1

    if not dry_run:
        print(f"purged {deleted} pair(s)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Retention and cleanup for agent-handoff runtime files")
    ap.add_argument("--status", action="store_true", help="Show disk usage and counts")
    ap.add_argument("--archive", action="store_true", help="Move old pairs to archive/YYYY-MM/")
    ap.add_argument("--purge", action="store_true", help="Hard-delete old pairs (irreversible)")
    ap.add_argument("--dry-run", action="store_true", help="Print actions without executing")
    ap.add_argument("--max-mb", type=float, default=None,
                    help="Abort if runtime data exceeds this size (MB)")
    args = ap.parse_args()

    root = HANDOFF_ROOT
    env = load_env(root)

    if args.status:
        return cmd_status(root, env)
    if args.archive:
        return cmd_archive(root, env, dry_run=args.dry_run, max_mb=args.max_mb)
    if args.purge:
        if not args.dry_run:
            confirm = input("Purge is irreversible. Type 'yes' to confirm: ").strip()
            if confirm != "yes":
                print("aborted")
                return 1
        return cmd_purge(root, env, dry_run=args.dry_run)

    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

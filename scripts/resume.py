#!/usr/bin/env python3
"""Watcher + resume launcher.

--watch              poll answers/ forever; resume sessions when answers arrive
--session-id <id>    one-shot resume of a specific session (reads HANDOFF.json for provider)
--provider <p>       force provider (claude|codex); defaults to HANDOFF.json or claude
--dry-run            print commands without executing

On new answer:
  1. Load question from questions/q_<id>.json
  2. Validate version + head_commit drift
  3. Run: claude -p --resume <session_id>   (Claude path)
         codex resume <session_id>          (Codex path)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from lib.core import (
    HANDOFF_ROOT,
    append_audit,
    is_replayed,
    load_active_session,
    load_env,
    read_answer,
    read_json,
    read_question,
    validate_answer,
    validate_answer_ttl,
)


# ---------------------------------------------------------------------------
# Provider resume
# ---------------------------------------------------------------------------

def resume_claude(session_id: str, dry_run: bool = False) -> int:
    cmd = ["claude", "-p", "--resume", session_id, "--bare"]
    if dry_run:
        print(f"[dry-run] {' '.join(cmd)}")
        return 0
    result = subprocess.run(cmd, stdin=subprocess.DEVNULL)
    return result.returncode


def resume_codex(session_id: str, dry_run: bool = False) -> int:
    cmd = ["codex", "resume", session_id]
    if dry_run:
        print(f"[dry-run] {' '.join(cmd)}")
        return 0
    result = subprocess.run(cmd, stdin=subprocess.DEVNULL)
    return result.returncode


PROVIDERS = {"claude": resume_claude, "codex": resume_codex}


def resume(provider: str, session_id: str, dry_run: bool = False) -> int:
    fn = PROVIDERS.get(provider)
    if not fn:
        print(f"unknown provider: {provider}", file=sys.stderr)
        return 2
    print(f"resuming {provider} session {session_id}")
    append_audit("resume_dispatched", session_id=session_id, provider=provider)
    rc = fn(session_id, dry_run)
    if rc == 0:
        append_audit("session_resumed_ok", session_id=session_id)
    else:
        append_audit("session_resume_failed", session_id=session_id, returncode=rc)
    return rc


# ---------------------------------------------------------------------------
# Answer processing
# ---------------------------------------------------------------------------

def _mark_consumed(root: Path, question_id: str) -> None:
    """Rename consumed answer so watcher doesn't re-trigger."""
    src = root / "answers" / f"{question_id}.json"
    dst = root / "answers" / f"{question_id}.consumed.json"
    try:
        os.replace(str(src), str(dst))
    except Exception:
        pass


def process_answer(root: Path, ans_path: Path, dry_run: bool = False) -> None:
    answer = read_json(ans_path)
    if not answer:
        print(f"skip {ans_path.name}: unreadable", file=sys.stderr)
        return

    question_id = answer.get("question_id")
    session_id = answer.get("session_id")
    if not question_id or not session_id:
        print(f"skip {ans_path.name}: missing question_id or session_id", file=sys.stderr)
        return

    question = read_question(root, question_id)
    if not question:
        print(f"skip {ans_path.name}: question file not found", file=sys.stderr)
        append_audit("answer_skipped", question_id=question_id, reason="question_not_found")
        return

    # Phase 4: replay guard
    if is_replayed(root, question_id):
        print(f"skip {ans_path.name}: already resumed (replay)", file=sys.stderr)
        append_audit("answer_replay_blocked", root=root, question_id=question_id)
        return

    # Phase 4: TTL guard
    env = load_env(root)
    ttl_ok, ttl_reason = validate_answer_ttl(question, env)
    if not ttl_ok:
        print(f"skip {ans_path.name}: {ttl_reason}", file=sys.stderr)
        append_audit("answer_ttl_blocked", root=root, question_id=question_id, reason=ttl_reason)
        return

    ok, reason = validate_answer(question, answer)
    if not ok:
        print(f"skip {ans_path.name}: {reason}", file=sys.stderr)
        append_audit("answer_rejected", question_id=question_id, reason=reason)
        return

    provider = question.get("provider", "claude")
    append_audit("answer_accepted", question_id=question_id, session_id=session_id, provider=provider)

    _mark_consumed(root, question_id)
    resume(provider, session_id, dry_run=dry_run)


# ---------------------------------------------------------------------------
# Watcher
# ---------------------------------------------------------------------------

def watch(root: Path, interval: int, dry_run: bool = False) -> int:
    answers_dir = root / "answers"
    print(f"watching {answers_dir} every {interval}s (dry_run={dry_run})")

    seen: set[str] = set()
    for p in answers_dir.glob("q_*.json"):
        seen.add(p.name)

    while True:
        try:
            for p in answers_dir.glob("q_*.json"):
                if p.name not in seen:
                    seen.add(p.name)
                    print(f"new answer: {p.name}")
                    process_answer(root, p, dry_run=dry_run)
        except Exception as e:
            print(f"watch error: {e}", file=sys.stderr)
        time.sleep(interval)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Watch for human answers and resume agent sessions."
    )
    ap.add_argument("--watch", action="store_true", help="poll answers/ forever")
    ap.add_argument("--session-id", help="one-shot resume of a specific session")
    ap.add_argument("--provider", default=None, choices=["claude", "codex"])
    ap.add_argument("--dry-run", action="store_true", help="print commands, don't run")
    args = ap.parse_args()

    root = HANDOFF_ROOT
    env = load_env(root)
    interval = int(env.get("HANDOFF_POLL_INTERVAL", "5"))

    if args.watch:
        return watch(root, interval, dry_run=args.dry_run)

    if args.session_id:
        provider = args.provider
        if not provider:
            state = load_active_session(root)
            provider = (state or {}).get("provider", "claude")
        return resume(provider, args.session_id, dry_run=args.dry_run)

    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

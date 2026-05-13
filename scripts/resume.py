#!/usr/bin/env python3
"""Watcher + resume launcher.

Modes:
  --watch                       poll answers/ forever, resume sessions when answers arrive
  --session-id <id>             one-shot resume of a specific session
  --provider [claude|codex]     defaults to value in state/active_session.json

PHASE 0 STUB. Phase 1 fills in real provider calls.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HANDOFF_ROOT = Path(__file__).resolve().parent.parent
ANSWERS = HANDOFF_ROOT / "answers"
QUESTIONS = HANDOFF_ROOT / "questions"
STATE = HANDOFF_ROOT / "state"


def resume_claude(session_id: str) -> int:
    # TODO Phase 1: invoke claude -p --resume <session_id> with proper stdin
    print(f"[stub] would run: claude -p --resume {session_id}")
    return 0


def resume_codex(session_id: str) -> int:
    # TODO Phase 3: codex resume <session_id>
    print(f"[stub] would run: codex resume {session_id}")
    return 0


def resume(provider: str, session_id: str) -> int:
    if provider == "claude":
        return resume_claude(session_id)
    if provider == "codex":
        return resume_codex(session_id)
    print(f"unknown provider: {provider}", file=sys.stderr)
    return 2


def find_new_answers(seen: set[str]) -> list[Path]:
    if not ANSWERS.exists():
        return []
    out = []
    for p in ANSWERS.glob("q_*.json"):
        if p.name not in seen:
            out.append(p)
    return out


def watch(interval: int) -> int:
    print(f"watching {ANSWERS} every {interval}s")
    seen: set[str] = set()
    for p in ANSWERS.glob("q_*.json"):
        seen.add(p.name)
    while True:
        new = find_new_answers(seen)
        for ans_path in new:
            seen.add(ans_path.name)
            try:
                ans = json.loads(ans_path.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"skip {ans_path.name}: {e}", file=sys.stderr)
                continue
            sid = ans.get("session_id")
            if not sid:
                continue
            # TODO Phase 1: read provider from questions/<qid>.json, validate version/commit
            resume("claude", sid)
        time.sleep(interval)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--session-id")
    ap.add_argument("--provider", default="claude", choices=["claude", "codex"])
    args = ap.parse_args()

    if args.watch:
        interval = int(os.environ.get("HANDOFF_POLL_INTERVAL", "5"))
        return watch(interval)
    if args.session_id:
        return resume(args.provider, args.session_id)
    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Codex SessionStart hook — inject latest unconsumed answer as additionalContext.

PHASE 0 STUB.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HANDOFF_ROOT = Path(__file__).resolve().parent.parent


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj))
    sys.stdout.flush()


def latest_unconsumed_answer(session_id: str) -> dict | None:
    # TODO Phase 3: scan answers/, filter by session_id + consumed flag in state/
    return None


def main() -> int:
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        emit({})
        return 0

    session_id = event.get("session_id", "")
    answer = latest_unconsumed_answer(session_id)
    if not answer:
        emit({})
        return 0

    emit({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": (
                f"Human answered pending question {answer['question_id']}: "
                f"{answer.get('summary', '')}. Continue from that answer."
            ),
        }
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

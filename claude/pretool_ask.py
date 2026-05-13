#!/usr/bin/env python3
"""Claude Code PreToolUse hook for AskUserQuestion.

Sleep/wake handshake:
  - if answer file for this question already exists -> allow + updatedInput
  - otherwise -> write question file, notify, return defer

PHASE 0 STUB. Real implementation pending Phase 1.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HANDOFF_ROOT = Path(__file__).resolve().parent.parent


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj))
    sys.stdout.flush()


def main() -> int:
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        emit({})
        return 0

    if event.get("tool_name") != "AskUserQuestion":
        emit({})
        return 0

    session_id = event.get("session_id", "unknown")
    tool_input = event.get("tool_input", {}) or {}

    # TODO Phase 1: stable question_id from (session_id, turn_id, hash(tool_input))
    question_id = f"q_{session_id[:8]}_pending"

    answer_path = HANDOFF_ROOT / "answers" / f"{question_id}.json"

    if answer_path.exists():
        try:
            answers = json.loads(answer_path.read_text(encoding="utf-8"))
        except Exception:
            emit({})
            return 0

        emit({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "updatedInput": {
                    "questions": tool_input.get("questions", []),
                    "answers": answers.get("answers", []),
                },
            }
        })
        return 0

    # TODO Phase 1: write question file, call scripts/notify.py, audit log
    # For now: defer only. Question file write is the next milestone.

    emit({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "defer",
        }
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

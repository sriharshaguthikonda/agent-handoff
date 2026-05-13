#!/usr/bin/env python3
"""Codex SessionStart hook — inject latest unconsumed answer as additionalContext.

Scans answers/ for a q_*.json file matching the current session_id that has NOT
been consumed (no .consumed.json counterpart). If found, injects the answer summary
so Codex can continue from where the human left off.

Note: this adds one new Codex turn. Strictly inferior to Claude's native defer path,
but it's the best available workaround for Codex CLI.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from lib.core import HANDOFF_ROOT, append_audit, read_json


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj))
    sys.stdout.flush()


def latest_unconsumed_answer(root: Path, session_id: str) -> dict | None:
    answers_dir = root / "answers"
    if not answers_dir.exists():
        return None
    consumed = {p.name.replace(".consumed.json", ".json") for p in answers_dir.glob("q_*.consumed.json")}
    for p in sorted(answers_dir.glob("q_*.json")):
        if p.name in consumed or ".consumed" in p.name:
            continue
        ans = read_json(p)
        if ans and ans.get("session_id") == session_id:
            return ans
    return None


def main() -> int:
    raw = sys.stdin.read()
    try:
        event = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        emit({})
        return 0

    session_id: str = event.get("session_id") or ""
    if not session_id:
        emit({})
        return 0

    root = HANDOFF_ROOT
    answer = latest_unconsumed_answer(root, session_id)
    if not answer:
        emit({})
        return 0

    qid = answer.get("question_id", "unknown")
    answers_list = answer.get("answers", [])
    answers_text = "; ".join(
        str(a.get("answer", a)) if isinstance(a, dict) else str(a)
        for a in answers_list
    )
    notes = answer.get("notes", "")
    context = f"Human answered pending question {qid}: {answers_text}."
    if notes:
        context += f" Notes: {notes}"
    context += " Continue from that answer."

    append_audit("answer_injected_codex", question_id=qid, session_id=session_id)

    emit({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

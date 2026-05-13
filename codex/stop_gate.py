#!/usr/bin/env python3
"""Codex Stop hook — detect [[QUESTION:q_<id>]] marker in last assistant message.

When Codex model emits [[QUESTION:q_<short-id>]], this hook:
  1. Writes questions/q_<id>.json
  2. Updates HANDOFF.md + HANDOFF.json
  3. Sends notifications
  4. Returns continue=false to pause the Codex session

The [[QUESTION:...]] marker must be followed by a one-line plain-text summary.
Format: [[QUESTION:q_<id>]] <one-line summary>
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from lib.core import (
    HANDOFF_ROOT,
    append_audit,
    load_env,
    save_active_session,
    write_handoff_state,
    write_question,
)

MARKER_RE = re.compile(r"\[\[QUESTION:(q_[a-zA-Z0-9_\-]+)\]\]\s*(.*?)$", re.MULTILINE)


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj))
    sys.stdout.flush()


def run_notify(root: Path, question_id: str, summary: str, env: dict) -> None:
    notify_env = {**env, "QUESTION_ID": question_id, "QUESTION_SUMMARY": summary}
    try:
        subprocess.run(
            [sys.executable, str(root / "scripts" / "notify.py")],
            env=notify_env,
            timeout=15,
            check=False,
            capture_output=True,
        )
    except Exception as e:
        sys.stderr.write(f"notify failed: {e}\n")


def main() -> int:
    raw = sys.stdin.read()
    try:
        event = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        emit({})
        return 0

    msg: str = event.get("last_assistant_message") or ""
    session_id: str = event.get("session_id") or "nosid"
    m = MARKER_RE.search(msg)
    if not m:
        emit({})
        return 0

    question_id: str = m.group(1)
    summary: str = m.group(2).strip() or "Agent needs input"
    root = HANDOFF_ROOT
    env = load_env(root)
    repo = env.get("REPO_PATH") or str(Path.cwd())

    # Build synthetic tool_input so question file has the text
    tool_input = {
        "questions": [{"question": summary, "header": "Question", "options": [], "multiSelect": False}]
    }

    write_question(root, question_id, session_id, "codex", tool_input, repo=repo)
    write_handoff_state(root, question_id, session_id, "codex", repo=repo)
    save_active_session(root, session_id, "codex", question_id)

    append_audit(
        "question_created",
        question_id=question_id,
        session_id=session_id,
        provider="codex",
        summary=summary,
    )
    run_notify(root, question_id, summary, env)
    append_audit("notification_sent", question_id=question_id)

    emit({
        "continue": False,
        "stopReason": f"Waiting for human answer in answers/{question_id}.json",
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

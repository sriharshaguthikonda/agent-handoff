#!/usr/bin/env python3
"""Claude Code PreToolUse hook for AskUserQuestion — BLOCKING variant.

Same-turn pause: hook polls answer file until answer arrives or timeout.
Session stays alive in same turn — no resume needed.

Config (via .env):
    HANDOFF_BLOCK_TIMEOUT  seconds to wait for answer (default 1800 = 30 min)
    HANDOFF_BLOCK_POLL     poll interval seconds (default 2.0)

On timeout: returns defer (falls back to resume-style flow via watcher).

Pair with a generous hook timeout in settings.json:
    {"type": "command", "command": "python .../pretool_ask_block.py", "timeout": 7200}
"""
from __future__ import annotations

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
    derive_question_id_stable,
    is_replayed,
    load_env,
    load_or_create_envelope_key,
    read_answer,
    read_question,
    save_active_session,
    validate_answer,
    validate_answer_ttl,
    verify_question_sig,
    write_handoff_state,
    write_question,
)


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj))
    sys.stdout.flush()


def run_notify(root: Path, question_id: str, summary: str, env: dict) -> None:
    notify_env = {**env, "QUESTION_ID": question_id, "QUESTION_SUMMARY": summary}
    notify_script = str(root / "scripts" / "notify.py")
    try:
        subprocess.run(
            [sys.executable, notify_script],
            env=notify_env,
            timeout=15,
            check=False,
            capture_output=True,
        )
    except Exception as e:
        sys.stderr.write(f"notify failed: {e}\n")


def _try_consume_answer(root: Path, question_id: str, session_id: str, tool_input: dict, env: dict):
    """Return allow-payload dict if answer present+valid, else None."""
    answer = read_answer(root, question_id)
    if answer is None:
        return None
    question = read_question(root, question_id)
    if question is None:
        return None

    if is_replayed(root, question_id):
        append_audit("answer_replay_rejected", question_id=question_id)
        return None

    ttl_ok, ttl_reason = validate_answer_ttl(question, env)
    if not ttl_ok:
        append_audit("answer_ttl_rejected", question_id=question_id, reason=ttl_reason)
        return None

    if "hmac_sig" in question:
        try:
            key = load_or_create_envelope_key(root)
            sig_ok, sig_reason = verify_question_sig(key, question)
            if not sig_ok:
                append_audit("answer_sig_rejected", question_id=question_id, reason=sig_reason)
                return None
        except Exception as e:
            sys.stderr.write(f"sig verify error (proceeding): {e}\n")

    ok, reason = validate_answer(question, answer)
    if not ok:
        append_audit("answer_rejected", question_id=question_id, reason=reason)
        return None

    append_audit("session_resumed", session_id=session_id, question_id=question_id, mode="block")
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": {
                "questions": tool_input.get("questions", []),
                "answers": answer.get("answers", []),
            },
        }
    }


def main() -> int:
    raw = sys.stdin.read()
    try:
        event = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        emit({})
        return 0

    if event.get("tool_name") != "AskUserQuestion":
        emit({})
        return 0

    session_id: str = event.get("session_id") or "nosid"
    tool_input: dict = event.get("tool_input") or {}
    root = HANDOFF_ROOT
    env = load_env(root)

    question_id = derive_question_id_stable(session_id, tool_input)

    payload = _try_consume_answer(root, question_id, session_id, tool_input, env)
    if payload is not None:
        emit(payload)
        return 0

    repo = env.get("REPO_PATH") or str(Path.cwd())
    write_question(root, question_id, session_id, "claude", tool_input, repo=repo)
    write_handoff_state(root, question_id, session_id, "claude", repo=repo)
    save_active_session(root, session_id, "claude", question_id)

    questions = tool_input.get("questions") or []
    summary = questions[0].get("question", "Agent needs input") if questions else "Agent needs input"
    append_audit(
        "question_created",
        question_id=question_id,
        session_id=session_id,
        provider="claude",
        mode="block",
        summary=summary,
    )

    run_notify(root, question_id, summary, env)
    append_audit("notification_sent", question_id=question_id)

    timeout = float(env.get("HANDOFF_BLOCK_TIMEOUT", "1800"))
    poll = float(env.get("HANDOFF_BLOCK_POLL", "2.0"))
    deadline = time.monotonic() + timeout

    append_audit("block_wait_started", question_id=question_id, timeout=timeout)

    while time.monotonic() < deadline:
        time.sleep(poll)
        payload = _try_consume_answer(root, question_id, session_id, tool_input, env)
        if payload is not None:
            append_audit("block_wait_resolved", question_id=question_id)
            emit(payload)
            return 0

    append_audit("block_wait_timeout", question_id=question_id)
    emit({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "defer",
        }
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

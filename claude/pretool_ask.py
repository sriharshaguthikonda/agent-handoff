#!/usr/bin/env python3
"""Claude Code PreToolUse hook for AskUserQuestion.

Sleep/wake handshake:
  no answer → write question file, notify, audit, return defer
  answer present → validate (TTL + replay + sig), return allow + updatedInput

Invoked by Claude Code in -p mode when AskUserQuestion fires.
Reads JSON from stdin (Claude hook contract).
Writes JSON to stdout.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
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

    # --- already have an answer? ---
    answer = read_answer(root, question_id)
    if answer is not None:
        question = read_question(root, question_id)
        if question is not None:
            # Phase 4: replay check
            if is_replayed(root, question_id):
                sys.stderr.write(f"replay rejected: {question_id} already accepted\n")
                append_audit("answer_replay_rejected", question_id=question_id)
                emit({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "defer"}})
                return 0

            # Phase 4: TTL check
            ttl_ok, ttl_reason = validate_answer_ttl(question, env)
            if not ttl_ok:
                sys.stderr.write(f"TTL rejected: {ttl_reason}\n")
                append_audit("answer_ttl_rejected", question_id=question_id, reason=ttl_reason)
                emit({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "defer"}})
                return 0

            # Phase 5: signature check (only if question was signed)
            if "hmac_sig" in question:
                try:
                    key = load_or_create_envelope_key(root)
                    sig_ok, sig_reason = verify_question_sig(key, question)
                    if not sig_ok:
                        sys.stderr.write(f"sig rejected: {sig_reason}\n")
                        append_audit("answer_sig_rejected", question_id=question_id, reason=sig_reason)
                        emit({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "defer"}})
                        return 0
                except Exception as e:
                    sys.stderr.write(f"sig verify error (proceeding): {e}\n")

            ok, reason = validate_answer(question, answer)
            if not ok:
                sys.stderr.write(f"stale answer rejected: {reason}\n")
                append_audit("answer_rejected", question_id=question_id, reason=reason)
                # fall through to re-defer
            else:
                append_audit("session_resumed", session_id=session_id, question_id=question_id)
                emit({
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "allow",
                        "updatedInput": {
                            "questions": tool_input.get("questions", []),
                            "answers": answer.get("answers", []),
                        },
                    }
                })
                return 0

    # --- no valid answer yet: write question, notify, defer ---
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
        summary=summary,
    )

    run_notify(root, question_id, summary, env)
    append_audit("notification_sent", question_id=question_id)

    emit({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "defer",
        }
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Codex Stop hook — detect [[QUESTION:q_<id>]] marker in last assistant message.

PHASE 0 STUB.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HANDOFF_ROOT = Path(__file__).resolve().parent.parent
MARKER_RE = re.compile(r"\[\[QUESTION:(q_[a-zA-Z0-9_\-]+)\]\]")


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj))
    sys.stdout.flush()


def main() -> int:
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        emit({})
        return 0

    msg = event.get("last_assistant_message") or ""
    m = MARKER_RE.search(msg)
    if not m:
        emit({})
        return 0

    question_id = m.group(1)
    # TODO Phase 3: write questions/q_<id>.json, notify, audit log

    emit({
        "continue": False,
        "stopReason": f"Waiting for human answer in answers/{question_id}.json",
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

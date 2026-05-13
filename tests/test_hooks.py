"""Integration tests for hook scripts via subprocess (no real Claude/Codex needed)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
PRETOOL = str(_REPO / "claude" / "pretool_ask.py")
STOPGATE = str(_REPO / "codex" / "stop_gate.py")
SESSION_START = str(_REPO / "codex" / "session_start.py")


def run_hook(script: str, stdin: str, env_extra: dict | None = None) -> dict:
    import os
    env = {**os.environ, "NOTIFY_TARGETS": "", **(env_extra or {})}
    result = subprocess.run(
        [sys.executable, script],
        input=stdin.encode(),
        capture_output=True,
        env=env,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr.decode()
    return json.loads(result.stdout.decode().strip() or "{}")


# ---------------------------------------------------------------------------
# pretool_ask.py
# ---------------------------------------------------------------------------

class TestPreToolAsk:
    def test_non_ask_passthrough(self, tmp_path: Path) -> None:
        event = {"tool_name": "Edit", "session_id": "s1", "tool_input": {}}
        out = run_hook(PRETOOL, json.dumps(event), {"HANDOFF_ROOT_OVERRIDE": str(tmp_path)})
        assert out == {}

    def test_empty_stdin(self, tmp_path: Path) -> None:
        out = run_hook(PRETOOL, "", {"HANDOFF_ROOT_OVERRIDE": str(tmp_path)})
        assert out == {}

    def test_defer_on_no_answer(self, tmp_path: Path) -> None:
        _setup_root(tmp_path)
        event = {
            "tool_name": "AskUserQuestion",
            "session_id": "sess_defer",
            "tool_input": {
                "questions": [{"question": "Which framework?", "header": "F", "options": []}]
            },
        }
        out = run_hook(PRETOOL, json.dumps(event), {"HANDOFF_ROOT_OVERRIDE": str(tmp_path)})
        hs = out.get("hookSpecificOutput", {})
        assert hs.get("permissionDecision") == "defer"
        # question file written
        questions = list((tmp_path / "questions").glob("q_*.json"))
        assert len(questions) == 1
        q = json.loads(questions[0].read_text())
        assert q["session_id"] == "sess_defer"
        assert q["status"] == "waiting_for_human"

    def test_allow_on_valid_answer(self, tmp_path: Path) -> None:
        _setup_root(tmp_path)
        from lib.core import derive_question_id_stable, write_question
        tool_input = {
            "questions": [{"question": "Pick one", "header": "P", "options": [{"label": "A"}]}]
        }
        sess = "sess_allow"
        qid = derive_question_id_stable(sess, tool_input)
        write_question(tmp_path, qid, sess, "claude", tool_input)
        # write valid answer
        ans = {
            "question_id": qid,
            "session_id": sess,
            "parent_version": 1,
            "head_commit_at_answer": "unknown",
            "answers": [{"answer": "A"}],
        }
        (tmp_path / "answers" / f"{qid}.json").write_text(json.dumps(ans))

        event = {
            "tool_name": "AskUserQuestion",
            "session_id": sess,
            "tool_input": tool_input,
        }
        out = run_hook(PRETOOL, json.dumps(event), {"HANDOFF_ROOT_OVERRIDE": str(tmp_path)})
        hs = out.get("hookSpecificOutput", {})
        assert hs.get("permissionDecision") == "allow"
        assert hs["updatedInput"]["answers"] == [{"answer": "A"}]


# ---------------------------------------------------------------------------
# stop_gate.py
# ---------------------------------------------------------------------------

class TestStopGate:
    def test_no_marker_passthrough(self, tmp_path: Path) -> None:
        event = {"last_assistant_message": "I finished the task.", "session_id": "s1"}
        out = run_hook(STOPGATE, json.dumps(event), {"HANDOFF_ROOT_OVERRIDE": str(tmp_path)})
        assert out == {}

    def test_marker_detected(self, tmp_path: Path) -> None:
        _setup_root(tmp_path)
        event = {
            "last_assistant_message": "[[QUESTION:q_mytest_001]] Which database to use?",
            "session_id": "sess_codex",
        }
        out = run_hook(STOPGATE, json.dumps(event), {"HANDOFF_ROOT_OVERRIDE": str(tmp_path)})
        assert out.get("continue") is False
        assert "q_mytest_001" in out.get("stopReason", "")
        # question file written
        q = json.loads((tmp_path / "questions" / "q_mytest_001.json").read_text())
        assert q["provider"] == "codex"
        assert "Which database" in q["context_summary"]


# ---------------------------------------------------------------------------
# session_start.py
# ---------------------------------------------------------------------------

class TestSessionStart:
    def test_no_answer(self, tmp_path: Path) -> None:
        _setup_root(tmp_path)
        event = {"session_id": "nosess"}
        out = run_hook(SESSION_START, json.dumps(event), {"HANDOFF_ROOT_OVERRIDE": str(tmp_path)})
        assert out == {}

    def test_injects_answer(self, tmp_path: Path) -> None:
        _setup_root(tmp_path)
        ans = {
            "question_id": "q_inject_001",
            "session_id": "sess_inject",
            "parent_version": 1,
            "head_commit_at_answer": "abc",
            "answers": [{"answer": "PostgreSQL"}],
            "notes": "preferred for OLTP",
        }
        (tmp_path / "answers" / "q_inject_001.json").write_text(json.dumps(ans))
        event = {"session_id": "sess_inject"}
        out = run_hook(SESSION_START, json.dumps(event), {"HANDOFF_ROOT_OVERRIDE": str(tmp_path)})
        ctx = out.get("hookSpecificOutput", {}).get("additionalContext", "")
        assert "PostgreSQL" in ctx
        assert "q_inject_001" in ctx

    def test_skips_consumed(self, tmp_path: Path) -> None:
        _setup_root(tmp_path)
        ans = {
            "question_id": "q_consumed_001",
            "session_id": "sess_c",
            "parent_version": 1,
            "answers": [{"answer": "yes"}],
        }
        (tmp_path / "answers" / "q_consumed_001.consumed.json").write_text(json.dumps(ans))
        event = {"session_id": "sess_c"}
        out = run_hook(SESSION_START, json.dumps(event), {"HANDOFF_ROOT_OVERRIDE": str(tmp_path)})
        assert out == {}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _setup_root(root: Path) -> None:
    for d in ["questions", "answers", "state", "audit", "handoff", "claude", "codex"]:
        (root / d).mkdir(exist_ok=True)
    (root / ".gitignore").write_text("")

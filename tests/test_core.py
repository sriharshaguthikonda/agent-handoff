"""Unit tests for lib.core — no subprocess, no Claude/Codex required."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from lib.core import (
    append_audit,
    atomic_write_json,
    derive_question_id_stable,
    read_answer,
    read_json,
    read_question,
    validate_answer,
    write_handoff_state,
    write_question,
)


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    for d in ["questions", "answers", "state", "audit", "handoff", "claude", "codex"]:
        (tmp_path / d).mkdir()
    (tmp_path / ".gitignore").write_text("")
    return tmp_path


# ---------------------------------------------------------------------------
# question_id stability
# ---------------------------------------------------------------------------

class TestQuestionId:
    def test_stable_same_inputs(self) -> None:
        a = derive_question_id_stable("sess1", {"questions": [{"question": "hi"}]})
        b = derive_question_id_stable("sess1", {"questions": [{"question": "hi"}]})
        assert a == b

    def test_different_session(self) -> None:
        a = derive_question_id_stable("sess1", {"questions": [{"question": "hi"}]})
        b = derive_question_id_stable("sess2", {"questions": [{"question": "hi"}]})
        assert a != b

    def test_different_body(self) -> None:
        a = derive_question_id_stable("sess1", {"questions": [{"question": "hi"}]})
        b = derive_question_id_stable("sess1", {"questions": [{"question": "bye"}]})
        assert a != b

    def test_starts_with_q(self) -> None:
        qid = derive_question_id_stable("s", {})
        assert qid.startswith("q_")


# ---------------------------------------------------------------------------
# Atomic JSON write
# ---------------------------------------------------------------------------

class TestAtomicWrite:
    def test_roundtrip(self, tmp_path: Path) -> None:
        p = tmp_path / "out.json"
        atomic_write_json(p, {"a": 1, "b": [2, 3]})
        assert read_json(p) == {"a": 1, "b": [2, 3]}

    def test_overwrites_existing(self, tmp_path: Path) -> None:
        p = tmp_path / "out.json"
        atomic_write_json(p, {"v": 1})
        atomic_write_json(p, {"v": 2})
        assert read_json(p) == {"v": 2}

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        p = tmp_path / "deep" / "nested" / "file.json"
        atomic_write_json(p, {"x": 42})
        assert read_json(p) == {"x": 42}


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

class TestAuditLog:
    def test_appends_line(self, root: Path) -> None:
        append_audit("test_event", root=root, foo="bar")
        lines = (root / "audit" / "events.jsonl").read_text().strip().splitlines()
        assert len(lines) == 1
        row = json.loads(lines[0])
        assert row["event"] == "test_event"
        assert row["foo"] == "bar"
        assert "ts" in row

    def test_multiple_appends(self, root: Path) -> None:
        append_audit("e1", root=root)
        append_audit("e2", root=root)
        append_audit("e3", root=root)
        lines = (root / "audit" / "events.jsonl").read_text().strip().splitlines()
        assert len(lines) == 3
        events = [json.loads(l)["event"] for l in lines]
        assert events == ["e1", "e2", "e3"]


# ---------------------------------------------------------------------------
# Question file
# ---------------------------------------------------------------------------

class TestQuestionFile:
    def test_write_read(self, root: Path) -> None:
        tool_input = {"questions": [{"question": "Which framework?", "header": "Framework", "options": []}]}
        qid = derive_question_id_stable("sess42", tool_input)
        write_question(root, qid, "sess42", "claude", tool_input, repo="/fake/repo")
        q = read_question(root, qid)
        assert q is not None
        assert q["question_id"] == qid
        assert q["session_id"] == "sess42"
        assert q["provider"] == "claude"
        assert q["status"] == "waiting_for_human"
        assert q["version"] == 1
        assert q["checksum"].startswith("sha256:")

    def test_question_file_exists_on_disk(self, root: Path) -> None:
        qid = "q_test_abc"
        write_question(root, qid, "s1", "claude", {})
        assert (root / "questions" / f"{qid}.json").exists()


# ---------------------------------------------------------------------------
# Answer validation
# ---------------------------------------------------------------------------

class TestAnswerValidation:
    def _q(self, **kwargs) -> dict:
        base = {
            "question_id": "q_abc",
            "session_id": "sess",
            "version": 1,
            "head_commit": "aabbccdd",
            "fallback_policy": "block_until_answer",
        }
        base.update(kwargs)
        return base

    def _a(self, **kwargs) -> dict:
        base = {
            "question_id": "q_abc",
            "session_id": "sess",
            "parent_version": 1,
            "head_commit_at_answer": "aabbccdd",
            "answers": [{"answer": "React"}],
        }
        base.update(kwargs)
        return base

    def test_valid(self) -> None:
        ok, reason = validate_answer(self._q(), self._a())
        assert ok
        assert reason == "ok"

    def test_qid_mismatch(self) -> None:
        ok, _ = validate_answer(self._q(), self._a(question_id="q_other"))
        assert not ok

    def test_stale_version(self) -> None:
        ok, reason = validate_answer(self._q(version=3), self._a(parent_version=2))
        assert not ok
        assert "parent_version" in reason

    def test_commit_drift_block_policy(self) -> None:
        ok, reason = validate_answer(
            self._q(fallback_policy="abandon_if_stale_after_head_change"),
            self._a(head_commit_at_answer="deadbeef"),
        )
        assert not ok
        assert "drifted" in reason

    def test_commit_drift_default_accepts(self) -> None:
        # default policy: warn but accept
        ok, _ = validate_answer(self._q(), self._a(head_commit_at_answer="deadbeef"))
        assert ok


# ---------------------------------------------------------------------------
# HANDOFF state
# ---------------------------------------------------------------------------

class TestHandoffState:
    def test_handoff_json_created(self, root: Path) -> None:
        write_question(root, "q_001", "sess", "claude", {})
        write_handoff_state(root, "q_001", "sess", "claude", repo="/r")
        h = read_json(root / "handoff" / "HANDOFF.json")
        assert h is not None
        assert h["active_session"]["session_id"] == "sess"
        assert h["active_session"]["blocking_question_id"] == "q_001"
        assert h["version"] == 1

    def test_handoff_md_created(self, root: Path) -> None:
        write_question(root, "q_002", "sess", "claude", {})
        write_handoff_state(root, "q_002", "sess", "claude", repo="/r")
        md = (root / "handoff" / "HANDOFF.md").read_text()
        assert "q_002" in md
        assert "sess" in md

    def test_version_increments(self, root: Path) -> None:
        write_question(root, "q_a", "s", "claude", {})
        write_handoff_state(root, "q_a", "s", "claude")
        write_question(root, "q_b", "s", "claude", {})
        write_handoff_state(root, "q_b", "s", "claude")
        h = read_json(root / "handoff" / "HANDOFF.json")
        assert h["version"] == 2

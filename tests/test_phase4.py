"""Tests for Phase 4 (integrity hardening) and Phase 5 (signed envelopes)."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from lib.core import (
    LockTimeout,
    append_audit,
    derive_question_id_stable,
    handoff_lock,
    is_replayed,
    load_or_create_envelope_key,
    sign_question,
    validate_answer,
    validate_answer_ttl,
    verify_question_sig,
    write_question,
)


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    for d in ["questions", "answers", "state", "audit", "handoff", "claude", "codex"]:
        (tmp_path / d).mkdir()
    (tmp_path / ".gitignore").write_text("")
    return tmp_path


# ---------------------------------------------------------------------------
# Phase 4: TTL validation
# ---------------------------------------------------------------------------

class TestTTL:
    def _q(self, created_offset_secs: float = 0.0) -> dict:
        from datetime import datetime, timezone, timedelta
        created = datetime.now(timezone.utc) + timedelta(seconds=created_offset_secs)
        return {
            "question_id": "q_ttl_test",
            "session_id": "s",
            "version": 1,
            "created_at": created.isoformat(),
        }

    def test_no_ttl_configured_always_passes(self) -> None:
        ok, _ = validate_answer_ttl(self._q(-9999), {})
        assert ok

    def test_within_ttl_passes(self) -> None:
        ok, _ = validate_answer_ttl(self._q(-10), {"HANDOFF_ANSWER_TTL": "3600"})
        assert ok

    def test_expired_ttl_rejected(self) -> None:
        ok, reason = validate_answer_ttl(self._q(-7200), {"HANDOFF_ANSWER_TTL": "3600"})
        assert not ok
        assert "TTL expired" in reason

    def test_invalid_ttl_value_ignored(self) -> None:
        ok, _ = validate_answer_ttl(self._q(-9999), {"HANDOFF_ANSWER_TTL": "not_a_number"})
        assert ok

    def test_missing_created_at_passes(self) -> None:
        ok, _ = validate_answer_ttl({}, {"HANDOFF_ANSWER_TTL": "60"})
        assert ok


# ---------------------------------------------------------------------------
# Phase 4: Replay detection
# ---------------------------------------------------------------------------

class TestReplayDetection:
    def test_no_audit_not_replayed(self, root: Path) -> None:
        assert not is_replayed(root, "q_never")

    def test_different_qid_not_replayed(self, root: Path) -> None:
        append_audit("answer_accepted", root=root, question_id="q_other", session_id="s1")
        assert not is_replayed(root, "q_different")

    def test_accepted_event_detected(self, root: Path) -> None:
        append_audit("answer_accepted", root=root, question_id="q_dup", session_id="s1")
        assert is_replayed(root, "q_dup")

    def test_non_accepted_event_not_detected(self, root: Path) -> None:
        append_audit("question_created", root=root, question_id="q_created", session_id="s1")
        assert not is_replayed(root, "q_created")

    def test_empty_audit_file_not_replayed(self, root: Path) -> None:
        (root / "audit" / "events.jsonl").write_text("")
        assert not is_replayed(root, "q_x")


# ---------------------------------------------------------------------------
# Phase 4: HANDOFF.json lock
# ---------------------------------------------------------------------------

class TestHandoffLock:
    def test_lock_acquires_and_releases(self, root: Path) -> None:
        with handoff_lock(root):
            lock_file = root / "handoff" / ".HANDOFF.lock"
            assert lock_file.exists()
        assert not lock_file.exists()

    def test_lock_is_exclusive(self, root: Path) -> None:
        with handoff_lock(root):
            with pytest.raises(LockTimeout):
                with handoff_lock(root, timeout=0.1):
                    pass

    def test_lock_released_on_exception(self, root: Path) -> None:
        lock_file = root / "handoff" / ".HANDOFF.lock"
        try:
            with handoff_lock(root):
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        assert not lock_file.exists()

    def test_second_lock_after_release(self, root: Path) -> None:
        with handoff_lock(root):
            pass
        with handoff_lock(root):
            pass  # should not raise


# ---------------------------------------------------------------------------
# Phase 5: Envelope signing
# ---------------------------------------------------------------------------

class TestEnvelopeSigning:
    def _q_obj(self) -> dict:
        return {
            "question_id": "q_sig_test",
            "session_id": "sess",
            "version": 1,
            "checksum": "sha256:abc123",
        }

    def test_key_generated(self, root: Path) -> None:
        key = load_or_create_envelope_key(root)
        assert isinstance(key, bytes)
        assert len(key) == 32

    def test_key_persists(self, root: Path) -> None:
        k1 = load_or_create_envelope_key(root)
        k2 = load_or_create_envelope_key(root)
        assert k1 == k2

    def test_sign_adds_hmac_sig(self, root: Path) -> None:
        key = load_or_create_envelope_key(root)
        obj = sign_question(key, self._q_obj())
        assert "hmac_sig" in obj
        assert len(obj["hmac_sig"]) == 64  # sha256 hex

    def test_verify_valid_sig(self, root: Path) -> None:
        key = load_or_create_envelope_key(root)
        obj = sign_question(key, self._q_obj())
        ok, reason = verify_question_sig(key, obj)
        assert ok
        assert reason == "ok"

    def test_verify_tampered_question_id(self, root: Path) -> None:
        key = load_or_create_envelope_key(root)
        obj = sign_question(key, self._q_obj())
        obj["question_id"] = "q_tampered"
        ok, reason = verify_question_sig(key, obj)
        assert not ok
        assert "mismatch" in reason

    def test_verify_wrong_key(self, root: Path) -> None:
        import secrets as _s
        key1 = load_or_create_envelope_key(root)
        key2 = _s.token_bytes(32)
        obj = sign_question(key1, self._q_obj())
        ok, _ = verify_question_sig(key2, obj)
        assert not ok

    def test_verify_no_sig_field(self, root: Path) -> None:
        key = load_or_create_envelope_key(root)
        ok, reason = verify_question_sig(key, self._q_obj())
        assert not ok
        assert "no hmac_sig" in reason

    def test_write_question_signed(self, root: Path) -> None:
        tool_input = {"questions": [{"question": "Which DB?", "header": "DB", "options": []}]}
        qid = derive_question_id_stable("sess", tool_input)
        write_question(root, qid, "sess", "claude", tool_input)
        q = json.loads((root / "questions" / f"{qid}.json").read_text())
        assert "hmac_sig" in q
        key = load_or_create_envelope_key(root)
        ok, _ = verify_question_sig(key, q)
        assert ok


# ---------------------------------------------------------------------------
# Phase 6: Edge cases — resume.py TTL + replay via process_answer()
# ---------------------------------------------------------------------------

sys.path.insert(0, str(_REPO / "scripts"))


class TestResumeEdgeCases:
    def test_replay_blocked_in_process_answer(self, tmp_path: Path) -> None:
        """process_answer skips answer if audit shows prior answer_accepted."""
        _setup_root(tmp_path)
        # import here so HANDOFF_ROOT_OVERRIDE applies inside the module
        import importlib
        import os as _os
        _os.environ["HANDOFF_ROOT_OVERRIDE"] = str(tmp_path)
        try:
            import scripts.resume as resume_mod
            importlib.reload(resume_mod)

            qid = "q_replay_test"
            (tmp_path / "questions" / f"{qid}.json").write_text(json.dumps({
                "question_id": qid, "session_id": "sess_replay",
                "version": 1, "head_commit": "unknown",
                "fallback_policy": "block_until_answer",
                "created_at": "2020-01-01T00:00:00+00:00",
                "provider": "claude",
            }))
            ans_path = tmp_path / "answers" / f"{qid}.json"
            ans_path.write_text(json.dumps({
                "question_id": qid, "session_id": "sess_replay",
                "parent_version": 1, "head_commit_at_answer": "unknown",
                "answers": [{"answer": "yes"}],
            }))
            # pre-populate audit with prior accept
            append_audit("answer_accepted", root=tmp_path, question_id=qid, session_id="sess_replay")

            resume_mod.process_answer(tmp_path, ans_path, dry_run=True)

            # audit should record replay block
            audit = (tmp_path / "audit" / "events.jsonl").read_text()
            assert "answer_replay_blocked" in audit
        finally:
            _os.environ.pop("HANDOFF_ROOT_OVERRIDE", None)

    def test_ttl_blocked_in_process_answer(self, tmp_path: Path) -> None:
        """process_answer skips answer if question is past TTL."""
        _setup_root(tmp_path)
        import importlib
        import os as _os
        _os.environ["HANDOFF_ROOT_OVERRIDE"] = str(tmp_path)
        _os.environ["HANDOFF_ANSWER_TTL"] = "3600"
        try:
            import scripts.resume as resume_mod
            importlib.reload(resume_mod)

            from datetime import datetime, timezone, timedelta
            qid = "q_ttl_resume"
            old_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
            (tmp_path / "questions" / f"{qid}.json").write_text(json.dumps({
                "question_id": qid, "session_id": "sess_ttl",
                "version": 1, "head_commit": "unknown",
                "fallback_policy": "block_until_answer",
                "created_at": old_time,
                "provider": "claude",
            }))
            ans_path = tmp_path / "answers" / f"{qid}.json"
            ans_path.write_text(json.dumps({
                "question_id": qid, "session_id": "sess_ttl",
                "parent_version": 1, "head_commit_at_answer": "unknown",
                "answers": [{"answer": "yes"}],
            }))

            resume_mod.process_answer(tmp_path, ans_path, dry_run=True)

            audit = (tmp_path / "audit" / "events.jsonl").read_text()
            assert "answer_ttl_blocked" in audit
        finally:
            _os.environ.pop("HANDOFF_ROOT_OVERRIDE", None)
            _os.environ.pop("HANDOFF_ANSWER_TTL", None)


# ---------------------------------------------------------------------------
# Phase 7: cleanup.py
# ---------------------------------------------------------------------------

CLEANUP = str(_REPO / "scripts" / "cleanup.py")


def _run_cleanup(args: list[str], env_extra: dict | None = None) -> subprocess.CompletedProcess:
    import os
    env = {**os.environ, **(env_extra or {})}
    return subprocess.run(
        [sys.executable, CLEANUP] + args,
        capture_output=True,
        env=env,
        timeout=10,
    )


class TestCleanup:
    def test_status_runs(self, tmp_path: Path) -> None:
        _setup_root(tmp_path)
        result = _run_cleanup(["--status"], {"HANDOFF_ROOT_OVERRIDE": str(tmp_path)})
        assert result.returncode == 0
        assert b"questions" in result.stdout.lower()

    def test_archive_dry_run_nothing(self, tmp_path: Path) -> None:
        _setup_root(tmp_path)
        result = _run_cleanup(
            ["--archive", "--dry-run"],
            {"HANDOFF_ROOT_OVERRIDE": str(tmp_path), "HANDOFF_RETENTION_DAYS": "30"},
        )
        assert result.returncode == 0
        assert b"nothing" in result.stdout.lower()

    def test_archive_moves_old_consumed_pair(self, tmp_path: Path) -> None:
        _setup_root(tmp_path)
        from datetime import datetime, timezone, timedelta
        old_ts = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
        qid = "q_old_001"
        (tmp_path / "questions" / f"{qid}.json").write_text(json.dumps({
            "question_id": qid, "session_id": "s", "version": 1,
            "created_at": old_ts,
        }))
        (tmp_path / "answers" / f"{qid}.consumed.json").write_text(json.dumps({
            "question_id": qid,
        }))
        result = _run_cleanup(
            ["--archive"],
            {"HANDOFF_ROOT_OVERRIDE": str(tmp_path), "HANDOFF_RETENTION_DAYS": "30"},
        )
        assert result.returncode == 0
        assert not (tmp_path / "questions" / f"{qid}.json").exists()
        archived = list((tmp_path / "archive").rglob(f"{qid}.json"))
        assert len(archived) == 1

    def test_purge_dry_run(self, tmp_path: Path) -> None:
        _setup_root(tmp_path)
        from datetime import datetime, timezone, timedelta
        old_ts = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
        qid = "q_purge_001"
        (tmp_path / "questions" / f"{qid}.json").write_text(json.dumps({
            "question_id": qid, "session_id": "s", "version": 1,
            "created_at": old_ts,
        }))
        (tmp_path / "answers" / f"{qid}.consumed.json").write_text("{}")
        result = _run_cleanup(
            ["--purge", "--dry-run"],
            {"HANDOFF_ROOT_OVERRIDE": str(tmp_path), "HANDOFF_RETENTION_DAYS": "30"},
        )
        assert result.returncode == 0
        assert b"dry-run" in result.stdout.lower()
        assert (tmp_path / "questions" / f"{qid}.json").exists()  # not deleted


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _setup_root(root: Path) -> None:
    for d in ["questions", "answers", "state", "audit", "handoff", "claude", "codex"]:
        (root / d).mkdir(exist_ok=True)
    (root / ".gitignore").write_text("")

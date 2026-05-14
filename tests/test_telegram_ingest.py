"""Tests for Telegram reply ingestion. No real Telegram calls."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from scripts import telegram_ingest


def _setup_root(root: Path) -> None:
    for d in ["questions", "answers", "state", "audit", "handoff", "claude", "codex"]:
        (root / d).mkdir(exist_ok=True)
    (root / ".gitignore").write_text("")


def _question(root: Path, qid: str = "q_test_001") -> dict:
    q = {
        "question_id": qid,
        "session_id": "sess_001",
        "version": 1,
        "head_commit": "unknown",
        "repo": "",
        "provider": "claude",
    }
    (root / "questions" / f"{qid}.json").write_text(json.dumps(q))
    return q


def _env(**kwargs) -> dict:
    base = {
        "TELEGRAM_BOT_TOKEN": "BOT:token",
        "TELEGRAM_CHAT_ID": "12345",
        "HANDOFF_TELEGRAM_POLL_INTERVAL": "1",
    }
    base.update(kwargs)
    return base


def _update(**kwargs) -> dict:
    message = {
        "message_id": 77,
        "chat": {"id": 12345},
        "from": {"id": 999},
        "text": "yes",
        "reply_to_message": {"text": "Agent blocked: q_test_001\nWhich framework?"},
    }
    message.update(kwargs.pop("message", {}))
    return {"update_id": kwargs.pop("update_id", 100), "message": message, **kwargs}


def _answer(root: Path, qid: str = "q_test_001") -> dict:
    return json.loads((root / "answers" / f"{qid}.json").read_text())


def test_reply_to_message_writes_answer(tmp_path: Path) -> None:
    _setup_root(tmp_path)
    _question(tmp_path)

    ok = telegram_ingest.process_update(tmp_path, _env(), _update())

    assert ok
    answer = _answer(tmp_path)
    assert answer["question_id"] == "q_test_001"
    assert answer["session_id"] == "sess_001"
    assert answer["parent_version"] == 1
    assert answer["answers"] == [{"answer": "yes"}]
    assert "source=telegram" in answer["notes"]
    audit = (tmp_path / "audit" / "events.jsonl").read_text()
    assert "telegram_answer_written" in audit
    assert "yes" not in audit


def test_leading_question_id_writes_answer(tmp_path: Path) -> None:
    _setup_root(tmp_path)
    _question(tmp_path)
    update = _update(message={
        "text": "q_test_001 use React",
        "reply_to_message": {},
    })

    ok = telegram_ingest.process_update(tmp_path, _env(), update)

    assert ok
    assert _answer(tmp_path)["answers"] == [{"answer": "use React"}]


def test_wrong_chat_ignored(tmp_path: Path) -> None:
    _setup_root(tmp_path)
    _question(tmp_path)
    update = _update(message={"chat": {"id": 54321}})

    ok = telegram_ingest.process_update(tmp_path, _env(), update)

    assert not ok
    assert not (tmp_path / "answers" / "q_test_001.json").exists()
    assert "wrong_chat" in (tmp_path / "audit" / "events.jsonl").read_text()


def test_wrong_allowed_user_ignored(tmp_path: Path) -> None:
    _setup_root(tmp_path)
    _question(tmp_path)

    ok = telegram_ingest.process_update(tmp_path, _env(TELEGRAM_ALLOWED_USER_ID="111"), _update())

    assert not ok
    assert not (tmp_path / "answers" / "q_test_001.json").exists()
    assert "wrong_user" in (tmp_path / "audit" / "events.jsonl").read_text()


def test_invalid_question_id_rejected(tmp_path: Path) -> None:
    _setup_root(tmp_path)
    update = _update(message={
        "text": "q_../../x answer",
        "reply_to_message": {},
    })

    ok = telegram_ingest.process_update(tmp_path, _env(), update)

    assert not ok
    assert not list((tmp_path / "answers").glob("*.json"))
    assert "missing_question_id" in (tmp_path / "audit" / "events.jsonl").read_text()


def test_missing_question_file_rejected(tmp_path: Path) -> None:
    _setup_root(tmp_path)

    ok = telegram_ingest.process_update(tmp_path, _env(), _update())

    assert not ok
    assert not (tmp_path / "answers" / "q_test_001.json").exists()
    assert "question_not_found" in (tmp_path / "audit" / "events.jsonl").read_text()


def test_existing_answer_not_overwritten(tmp_path: Path) -> None:
    _setup_root(tmp_path)
    _question(tmp_path)
    existing = {
        "question_id": "q_test_001",
        "session_id": "sess_001",
        "parent_version": 1,
        "answers": [{"answer": "old"}],
        "head_commit_at_answer": "unknown",
    }
    (tmp_path / "answers" / "q_test_001.json").write_text(json.dumps(existing))

    ok = telegram_ingest.process_update(tmp_path, _env(), _update(message={"text": "new"}))

    assert not ok
    assert _answer(tmp_path)["answers"] == [{"answer": "old"}]
    assert "answer_exists" in (tmp_path / "audit" / "events.jsonl").read_text()


def test_poll_once_advances_offset_for_handled_and_rejected_updates(tmp_path: Path) -> None:
    _setup_root(tmp_path)
    _question(tmp_path)
    updates = [
        _update(update_id=200, message={"text": "ok"}),
        _update(update_id=201, message={"chat": {"id": 54321}, "text": "ignored"}),
    ]

    with patch("scripts.telegram_ingest.fetch_updates", return_value=updates) as mock_fetch:
        written = telegram_ingest.poll_once(tmp_path, _env())

    assert written == 1
    mock_fetch.assert_called_once_with("BOT:token", 1)
    state = json.loads((tmp_path / "state" / "telegram_ingest.json").read_text())
    assert state["last_update_id"] == 201


def test_disabled_ingest_skips_fetch(tmp_path: Path) -> None:
    _setup_root(tmp_path)

    with patch("scripts.telegram_ingest.fetch_updates") as mock_fetch:
        written = telegram_ingest.poll_once(tmp_path, _env(HANDOFF_TELEGRAM_INGEST_ENABLED="0"))

    assert written == 0
    mock_fetch.assert_not_called()

"""Tests for notify.py — mocked HTTP, no real network calls."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from scripts.notify import load_env, send_ntfy, send_slack, send_telegram


def _env(**kwargs) -> dict:
    base = {
        "NTFY_URL": "https://ntfy.sh/test-topic",
        "TELEGRAM_BOT_TOKEN": "BOT:token",
        "TELEGRAM_CHAT_ID": "12345",
        "SLACK_WEBHOOK_URL": "https://hooks.slack.com/test",
        "BURNTTOAST_ENABLED": "0",
        "NOTIFY_TARGETS": "ntfy,telegram,slack",
    }
    base.update(kwargs)
    return base


def _payload(**kwargs) -> dict:
    base = {"question_id": "q_test_001", "summary": "Which framework?"}
    base.update(kwargs)
    return base


class TestNtfy:
    def test_skips_placeholder_url(self) -> None:
        env = _env(NTFY_URL="https://ntfy.sh/REPLACE-ME-LONG-RANDOM-TOPIC")
        ok = send_ntfy(env, _payload())
        assert not ok

    def test_skips_empty_url(self) -> None:
        ok = send_ntfy(_env(NTFY_URL=""), _payload())
        assert not ok

    def test_posts_to_ntfy(self) -> None:
        with patch("urllib.request.urlopen") as mock_open:
            mock_open.return_value.__enter__ = lambda s: s
            mock_open.return_value.__exit__ = MagicMock(return_value=False)
            mock_open.return_value.read = MagicMock(return_value=b"")
            ok = send_ntfy(_env(), _payload())
        assert ok
        req = mock_open.call_args[0][0]
        assert "ntfy.sh/test-topic" in req.full_url
        assert req.get_header("Title") == "Agent blocked: q_test_001"


class TestTelegram:
    def test_skips_empty_token(self) -> None:
        ok = send_telegram(_env(TELEGRAM_BOT_TOKEN=""), _payload())
        assert not ok

    def test_skips_empty_chat(self) -> None:
        ok = send_telegram(_env(TELEGRAM_CHAT_ID=""), _payload())
        assert not ok

    def test_posts_to_telegram(self) -> None:
        with patch("urllib.request.urlopen") as mock_open:
            mock_open.return_value.__enter__ = lambda s: s
            mock_open.return_value.__exit__ = MagicMock(return_value=False)
            mock_open.return_value.read = MagicMock(return_value=b"")
            ok = send_telegram(_env(), _payload())
        assert ok
        req = mock_open.call_args[0][0]
        assert "BOT:token/sendMessage" in req.full_url
        body = json.loads(req.data.decode())
        assert body["chat_id"] == "12345"
        assert "q_test_001" in body["text"]


class TestSlack:
    def test_skips_empty_url(self) -> None:
        ok = send_slack(_env(SLACK_WEBHOOK_URL=""), _payload())
        assert not ok

    def test_posts_to_slack(self) -> None:
        with patch("urllib.request.urlopen") as mock_open:
            mock_open.return_value.__enter__ = lambda s: s
            mock_open.return_value.__exit__ = MagicMock(return_value=False)
            mock_open.return_value.read = MagicMock(return_value=b"")
            ok = send_slack(_env(), _payload())
        assert ok
        req = mock_open.call_args[0][0]
        assert "slack.com" in req.full_url
        body = json.loads(req.data.decode())
        assert "q_test_001" in body["text"]


class TestSubprocessRun:
    def test_notify_script_runs(self, tmp_path: Path) -> None:
        """Script exits 0 with NOTIFY_TARGETS='' (no actual network calls)."""
        import os
        env = {
            **os.environ,
            "NOTIFY_TARGETS": "",
            "QUESTION_ID": "q_test_sub",
            "QUESTION_SUMMARY": "test summary",
            "HANDOFF_ROOT_OVERRIDE": str(tmp_path),
        }
        result = subprocess.run(
            [sys.executable, str(_REPO / "scripts" / "notify.py")],
            input=b"",
            capture_output=True,
            env=env,
            timeout=10,
        )
        assert result.returncode == 0
        out = json.loads(result.stdout.decode())
        assert "notify_results" in out
        assert out["notify_results"] == {}

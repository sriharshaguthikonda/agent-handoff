#!/usr/bin/env python3
"""Poll Telegram replies and write answers/q_<id>.json.

This is an inbound edge adapter only. It validates Telegram update metadata,
extracts a question id, writes the normal answer file, and lets the existing
Claude/Codex resume paths consume it.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from lib.core import (
    HANDOFF_ROOT,
    append_audit,
    atomic_write_json,
    is_valid_question_id,
    load_env,
    read_json,
    read_question,
    write_answer,
)


def _state_path(root: Path) -> Path:
    return root / "state" / "telegram_ingest.json"


def load_offset(root: Path) -> int:
    state = read_json(_state_path(root)) or {}
    try:
        return int(state.get("last_update_id", 0))
    except Exception:
        return 0


def save_offset(root: Path, update_id: int) -> None:
    atomic_write_json(_state_path(root), {
        "last_update_id": update_id,
        "updated_at_unix": int(time.time()),
    })


def fetch_updates(token: str, offset: int, timeout: int = 3) -> list[dict]:
    query = urllib.parse.urlencode({
        "offset": offset,
        "timeout": timeout,
        "allowed_updates": json.dumps(["message"]),
    })
    url = f"https://api.telegram.org/bot{token}/getUpdates?{query}"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout + 5) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not data.get("ok"):
        raise RuntimeError("telegram getUpdates returned ok=false")
    return data.get("result", [])


def extract_question_id(message: dict) -> tuple[str | None, str]:
    text = (message.get("text") or "").strip()
    reply = message.get("reply_to_message") or {}
    reply_text = (reply.get("text") or "").strip()

    for token in reply_text.replace("\n", " ").split():
        clean = token.strip("`.,:;()[]")
        if is_valid_question_id(clean):
            return clean, text

    if text:
        first, _, rest = text.partition(" ")
        clean = first.strip("`.,:;()[]")
        if is_valid_question_id(clean):
            return clean, rest.strip()

    return None, text


def _matches_allowed_user(message: dict, allowed_user_id: str) -> bool:
    if not allowed_user_id:
        return True
    sender = message.get("from") or {}
    return str(sender.get("id", "")) == allowed_user_id


def process_update(root: Path, env: dict, update: dict) -> bool:
    update_id = update.get("update_id")
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    expected_chat = env.get("TELEGRAM_CHAT_ID", "").strip()
    allowed_user = env.get("TELEGRAM_ALLOWED_USER_ID", "").strip()

    if expected_chat and str(chat.get("id", "")) != expected_chat:
        append_audit("telegram_update_ignored", root=root, update_id=update_id, reason="wrong_chat")
        return False
    if not _matches_allowed_user(message, allowed_user):
        append_audit("telegram_update_ignored", root=root, update_id=update_id, reason="wrong_user")
        return False

    question_id, answer_text = extract_question_id(message)
    if not question_id:
        append_audit("telegram_update_ignored", root=root, update_id=update_id, reason="missing_question_id")
        return False
    if not answer_text:
        append_audit("telegram_update_ignored", root=root, update_id=update_id, question_id=question_id, reason="empty_answer")
        return False

    question = read_question(root, question_id)
    if not question:
        append_audit("telegram_update_ignored", root=root, update_id=update_id, question_id=question_id, reason="question_not_found")
        return False

    try:
        path = write_answer(
            root,
            question,
            answer_text,
            "telegram",
            {
                "update_id": update_id,
                "message_id": message.get("message_id"),
            },
        )
    except FileExistsError:
        append_audit("telegram_update_ignored", root=root, update_id=update_id, question_id=question_id, reason="answer_exists")
        return False
    except Exception as exc:
        append_audit("telegram_update_ignored", root=root, update_id=update_id, question_id=question_id, reason=type(exc).__name__)
        return False

    append_audit(
        "telegram_answer_written",
        root=root,
        question_id=question_id,
        update_id=update_id,
        message_id=message.get("message_id"),
        answer_file=path.name,
    )
    return True


def poll_once(root: Path, env: dict) -> int:
    enabled = env.get("HANDOFF_TELEGRAM_INGEST_ENABLED", "1").strip().lower()
    if enabled in {"0", "false", "no", "off"}:
        print("telegram ingest disabled by HANDOFF_TELEGRAM_INGEST_ENABLED", file=sys.stderr)
        return 0

    token = env.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = env.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        print("telegram ingest skipped: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing", file=sys.stderr)
        return 0

    last = load_offset(root)
    updates = fetch_updates(token, last + 1)
    written = 0
    for update in updates:
        update_id = int(update.get("update_id", 0))
        try:
            if process_update(root, env, update):
                written += 1
        finally:
            if update_id:
                save_offset(root, update_id)
    return written


def watch(root: Path, env: dict) -> int:
    interval = int(env.get("HANDOFF_TELEGRAM_POLL_INTERVAL", "5"))
    print(f"watching Telegram replies every {interval}s")
    while True:
        try:
            poll_once(root, env)
        except Exception as exc:
            print(f"telegram ingest error: {exc}", file=sys.stderr)
        time.sleep(interval)


def main() -> int:
    ap = argparse.ArgumentParser(description="Poll Telegram replies into answers/q_<id>.json.")
    ap.add_argument("--once", action="store_true", help="poll Telegram once and exit")
    ap.add_argument("--watch", action="store_true", help="poll Telegram forever")
    args = ap.parse_args()

    root = HANDOFF_ROOT
    env = load_env(root)
    if args.watch:
        return watch(root, env)
    poll_once(root, env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

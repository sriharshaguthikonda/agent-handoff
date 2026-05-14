# Telegram Reply Ingest Plan

## Goal

Make this real:

```
Agent asks question -> Telegram notification arrives -> user replies in Telegram
-> repo writes answers/q_<id>.json -> existing block/defer resume path continues
```

Current state: Telegram is outbound-only. `scripts/notify.py` sends `sendMessage`; nothing reads Telegram updates or writes `answers/q_<id>.json`.

## Recommended Design

Use Telegram `getUpdates` polling first, not webhooks.

Reason: this repo is local-first and Windows-primary. Polling needs only the existing bot token and works without public HTTPS, reverse tunnels, firewall rules, or a hosted relay. Webhook mode can be added later behind the same parser.

## File Targets

- `scripts/telegram_ingest.py`
  - New stdlib-only CLI.
  - Supports `--once` and `--watch`.
  - Reads `.env` through existing `lib.core.load_env`.
  - Calls Telegram `getUpdates`.
  - Writes valid `answers/q_<id>.json`.
  - Stores update offset in `state/telegram_ingest.json`.

- `scripts/install_telegram_ingest_windows.ps1`
  - Optional Windows Scheduled Task installer.
  - Run `python C:/AI/agent-handoff/scripts/telegram_ingest.py --watch`.
  - Use absolute executable and script paths.

- `scripts/notify.py`
  - Keep outbound payload short.
  - Include `reply_markup.force_reply` so Telegram clients naturally reply to the bot message.
  - Keep question id visible in message text: `Agent blocked: q_<id>`.

- `lib/core.py`
  - Add a small helper if useful:
    - `is_valid_question_id(question_id) -> bool`
    - `write_answer(root, question, answer_text, source, metadata=None) -> Path`
  - The helper should derive schema from the question file and use `atomic_write_json`.
  - Do not add a broad abstraction unless tests show duplicate answer-writing code.

- `.env.example`
  - Add planned ingest settings:
    - `TELEGRAM_ALLOWED_USER_ID=`
    - `HANDOFF_TELEGRAM_POLL_INTERVAL=5`
    - `HANDOFF_TELEGRAM_INGEST_ENABLED=0`

- `tests/test_telegram_ingest.py`
  - New test file with mocked Telegram HTTP.

## Answer Binding Rules

Only write an answer when the question id is unambiguous.

Accepted:
- User replies directly to the bot's notification message, and `reply_to_message.text` contains `q_<id>`.
- User sends `q_<id> <answer text>` as a normal message.

Rejected:
- Wrong `chat.id`.
- Wrong `from.id` when `TELEGRAM_ALLOWED_USER_ID` is set.
- Missing or invalid question id.
- Question file missing.
- Existing `answers/q_<id>.json` already present.
- Empty answer text.
- Question id fails regex `^q_[A-Za-z0-9_]+$`.

Do not implement "single pending question fallback" by default. It can write the wrong answer when multiple agents are blocked.

## Answer File Schema

Given `questions/q_0bc43eadb4ef54d1.json` and Telegram text `include the recovery action`, write:

```json
{
  "question_id": "q_0bc43eadb4ef54d1",
  "session_id": "<from question file>",
  "parent_version": 1,
  "answered_at": "<UTC ISO timestamp>",
  "answers": [{"answer": "include the recovery action"}],
  "notes": "source=telegram update_id=<id> message_id=<id>",
  "head_commit_at_answer": "<current HEAD for question.repo, or question.head_commit, or unknown>"
}
```

Use `get_git_info(question["repo"])` for `head_commit_at_answer` when possible. Fall back to the question's `head_commit`, then `unknown`.

## Ingest Flow

1. Load `.env`.
2. Exit unless bot token and chat id are configured.
3. Read `state/telegram_ingest.json` for the last processed update offset.
4. Call `getUpdates?offset=<last_offset + 1>&timeout=<short timeout>`.
5. For each message:
   - Validate chat/user.
   - Extract `question_id` from `reply_to_message.text` or leading text.
   - Validate question id regex before building any path.
   - Load `questions/q_<id>.json`.
   - Build the answer object.
   - Write via atomic rename to `answers/q_<id>.json`.
   - Append audit event `telegram_answer_written` without answer text.
   - Advance offset even for rejected updates, after logging why.
6. In `--watch`, sleep `HANDOFF_TELEGRAM_POLL_INTERVAL` and repeat.

Existing behavior then takes over:
- Claude block mode sees the answer file while polling and returns `allow`.
- Claude defer mode has `scripts/resume.py --watch` resume the session.
- Codex resume path sees the same answer file through `codex/session_start.py`.

## Security Rules

- Never log full answer text in `audit/events.jsonl`.
- Never accept file paths from Telegram text.
- Never evaluate Telegram text.
- Never overwrite an existing answer file.
- Never send question body, tool output, secrets, or private file contents in outbound Telegram notifications.
- Keep token values in `.env` only; do not commit real tokens.

## Tests

Add focused tests with no real network:

- Reply-to-message with `q_<id>` writes `answers/q_<id>.json`.
- Leading `q_<id> answer` writes the same schema.
- Wrong chat is ignored.
- Wrong `TELEGRAM_ALLOWED_USER_ID` is ignored.
- Invalid qid such as `q_../../x` is rejected.
- Missing question file is rejected.
- Existing answer file is not overwritten.
- Offset is advanced after handled and rejected updates.
- `send_telegram` includes `force_reply` and still includes the qid in text.

Run:

```powershell
python -m pytest tests/test_telegram_ingest.py tests/test_notify.py tests/test_phase4.py
```

## Manual Verification

1. Start answer watcher:

```powershell
python C:/AI/agent-handoff/scripts/resume.py --watch
```

2. Start Telegram ingest:

```powershell
python C:/AI/agent-handoff/scripts/telegram_ingest.py --watch
```

3. Trigger a real blocked question.
4. Reply to the Telegram bot message.
5. Confirm the answer file exists:

```powershell
Get-ChildItem C:/AI/agent-handoff/answers/q_*.json
```

6. Confirm audit has a non-content event:

```powershell
Get-Content C:/AI/agent-handoff/audit/events.jsonl | Select-String telegram_answer_written
```

## Acceptance Criteria

- A Telegram reply to a bot question creates exactly one matching `answers/q_<id>.json`.
- The answer file passes existing `validate_answer` checks.
- The existing Claude block/defer and Codex resume paths need no special Telegram code.
- Rejected Telegram updates cannot create files outside `answers/`.
- Tests pass with mocked network calls.

# Architecture

## Three separate states

Mixing these is the #1 failure mode. Keep them split.

| State | What | Where | Lifecycle |
|-------|------|-------|-----------|
| Workspace state | Files on disk, repo HEAD, branch | Git | Per repo |
| Conversation state | Model turns, tool calls, transcripts | Provider-native (`~/.claude/projects`, `~/.codex/`) | Per session |
| Handoff state | Pending questions, human answers, status | `agent-handoff/handoff/`, `questions/`, `answers/` | Per question |

## Data contracts

### `questions/q_<id>.json` (agent → human)

```json
{
  "question_id": "q_20260513_001",
  "session_id": "abc123",
  "provider": "claude",
  "tool": "AskUserQuestion",
  "repo": "C:/AI/some-project",
  "branch": "main",
  "head_commit": "deadbeef",
  "created_at": "2026-05-13T14:00:00Z",
  "status": "waiting_for_human",
  "severity": "blocking",
  "fallback_policy": "block_until_answer",
  "questions": [
    {
      "question": "Which framework?",
      "header": "Framework",
      "options": [{"label": "React"}, {"label": "Vue"}],
      "multiSelect": false
    }
  ],
  "context_summary": "One-line plain English so notification body has signal.",
  "version": 1,
  "checksum": "sha256:..."
}
```

### `answers/q_<id>.json` (human → agent)

```json
{
  "question_id": "q_20260513_001",
  "session_id": "abc123",
  "parent_version": 1,
  "answered_at": "2026-05-13T14:05:00Z",
  "answers": [{"answer": "React"}],
  "notes": "Optional free text",
  "head_commit_at_answer": "deadbeef"
}
```

### `handoff/HANDOFF.json` (canonical machine state)

Single-writer. Always describes latest session resume target.

```json
{
  "version": 7,
  "active_session": {
    "provider": "claude",
    "session_id": "abc123",
    "repo": "C:/AI/some-project",
    "branch": "main",
    "head_commit": "deadbeef",
    "status": "waiting_for_human",
    "blocking_question_id": "q_20260513_001"
  },
  "updated_at": "2026-05-13T14:00:01Z",
  "checksum": "sha256:..."
}
```

### `audit/events.jsonl` (append-only)

```
{"ts":"2026-05-13T14:00:00Z","event":"question_created","question_id":"q_...","session_id":"abc123","provider":"claude"}
{"ts":"2026-05-13T14:00:01Z","event":"notification_sent","question_id":"q_...","channels":["ntfy","telegram"]}
{"ts":"2026-05-13T14:05:00Z","event":"answer_received","question_id":"q_..."}
{"ts":"2026-05-13T14:05:02Z","event":"session_resumed","session_id":"abc123"}
```

## Sleep / wake flow (Claude — native path)

```
1. Agent calls AskUserQuestion tool
2. PreToolUse hook fires (claude/pretool_ask.py)
3. Hook writes questions/q_<id>.json + HANDOFF.md + audit event
4. Hook calls scripts/notify.py (fan-out to ntfy + Telegram + toast + Slack)
5. Hook returns {"permissionDecision": "defer"}
6. Claude exits with stop_reason: "tool_deferred", saves deferred_tool_use to session
7. Watcher (scripts/resume.py daemon) polls answers/ every N seconds
8. Human writes answers/q_<id>.json (direct file edit or Telegram reply ingest)
9. Watcher validates: parent_version matches, head_commit matches (or forced reconcile)
10. Watcher runs: claude -p --resume <session_id>
11. PreToolUse hook fires again on the SAME deferred AskUserQuestion
12. Hook sees answers/q_<id>.json present → returns {"permissionDecision": "allow", "updatedInput": {...}}
13. Claude resumes from exactly where it was. Zero transcript replay.
```

## Sleep / wake flow (Codex — workaround path)

```
1. Agent emits assistant message containing [[QUESTION:q_<id>]] marker
2. Stop hook (codex/stop_gate.py) detects marker in last_assistant_message
3. Hook writes questions/q_<id>.json + notify + audit
4. Hook returns {"continue": false, "stopReason": "..."}  (session pauses)
5. Watcher polls answers/
6. Human writes answers/q_<id>.json
7. Watcher runs: codex resume <session_id>
8. SessionStart hook (codex/session_start.py) injects answer via additionalContext
9. Codex continues. Note: this DOES add one new turn — strictly inferior to Claude path
```

## Inbound answer ingest target

All human-input channels must converge on the same file contract: `answers/q_<id>.json`.

Telegram reply ingest should be a small edge adapter:

```
1. Telegram notification message includes q_<id>
2. User replies to that message
3. scripts/telegram_ingest.py polls getUpdates
4. Ingest validates chat/user + qid regex + question file
5. Ingest writes answers/q_<id>.json by atomic rename
6. Existing Claude/Codex resume code consumes the answer file
```

Webhook mode is not the current implementation target. Local polling is preferred until this repo intentionally grows a public HTTPS endpoint.

## Integrity rules

- JSON sidecars written via **atomic rename** (write to `.tmp`, fsync, rename)
- Monotonic `version` on `HANDOFF.json`
- `audit/events.jsonl` is append-only, never rewritten
- Pin every question to `session_id + branch + commit`
- Reject answers where `parent_version` < latest question version
- Reject answers where `head_commit` differs from current repo HEAD unless `fallback_policy = ignore_drift`

## Threat model (summary — see `THREAT_MODEL.md` for full)

| Threat | Mitigation |
|--------|------------|
| Sensitive prompt leakage via notification | Notification carries question_id + short summary only. Full content stays on disk. |
| Answer tampering / replay | Version + branch/commit anchors. Optional HMAC envelope (Phase 5). |
| Path traversal via model output | All file paths derived from `question_id` (regex-validated), never from tool input. |
| Local plaintext exposure | Owner-only perms on `answers/`. Encrypted disk recommended. `.env` for tokens. |
| Hook runs with full user perms | Adapters validate input, quote shell vars, never `eval` model output. |

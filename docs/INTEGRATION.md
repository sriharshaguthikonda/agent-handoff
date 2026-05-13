# Integration guide

## Claude Code wiring

### Merge hooks into a target repo (safe — never overwrites)

```bash
# Adds only the missing hook entries; backs up existing settings.json first.
python C:/AI/agent-handoff/scripts/merge_settings.py --target /path/to/target-repo
```

To merge into the **global** Claude settings (applies to all repos):

```bash
python C:/AI/agent-handoff/scripts/merge_settings.py --global
```

Preview without writing:

```bash
python C:/AI/agent-handoff/scripts/merge_settings.py --target /repo --dry-run
```

The script appends only entries whose `command` string is not already present —
running it twice is idempotent. A `.bak` copy of the original file is created before any write.

### What gets merged

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "AskUserQuestion",
        "hooks": [{"type": "command", "command": "python C:/AI/agent-handoff/claude/pretool_ask.py"}]
      }
    ],
    "Notification": [
      {
        "matcher": "permission_prompt|idle_prompt",
        "hooks": [{"type": "command", "command": "python C:/AI/agent-handoff/scripts/notify.py"}]
      }
    ]
  }
}
```

### Non-interactive only

`defer` works in `claude -p` mode only. Interactive sessions fall back to writing the question file + notifying; the session continues and the human can answer in the terminal as normal. The handoff path adds value for long autonomous runs.

---

## Codex CLI wiring

### Enable hooks (feature flag)

In `~/.codex/config.toml`:

```toml
[features]
codex_hooks = true
```

### `~/.codex/hooks.json`

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python C:/AI/agent-handoff/codex/stop_gate.py",
            "timeout": 30
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "matcher": "startup|resume",
        "hooks": [
          {
            "type": "command",
            "command": "python C:/AI/agent-handoff/codex/session_start.py",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

### Codex prompt prefix

Add to the system prompt (or `AGENTS.md` of target repo):

> When you need a human decision before continuing, emit exactly one line containing `[[QUESTION:q_<short-id>]]` followed by a one-line plain English summary. Do not ask multiple unrelated questions in one turn.

---

## Watcher daemon

`scripts/resume.py` runs as a background process. Options:

| OS | Mechanism |
|----|-----------|
| Windows | Scheduled Task — `powershell -ExecutionPolicy Bypass -File scripts/install_watcher_windows.ps1` |
| Linux | systemd user unit (`agent-handoff.service` + `.timer`) |
| macOS | launchd plist |

Manual start: `python C:/AI/agent-handoff/scripts/resume.py --watch`

---

## Notification setup

Copy `.env.example` → `.env` and fill in tokens:

```
NTFY_URL=https://ntfy.sh/your-private-topic-here
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
SLACK_WEBHOOK_URL=...
BURNTTOAST_ENABLED=1
NOTIFY_TARGETS=ntfy,telegram,burnttoast,slack
```

`notify.py` reads `.env` and fans out. Missing tokens skip silently.

---

## Integrity options (.env)

| Variable | Default | Meaning |
|----------|---------|---------|
| `HANDOFF_ANSWER_TTL` | *(none)* | Reject answers to questions older than N seconds |
| `HANDOFF_RETENTION_DAYS` | `30` | `cleanup.py` archives pairs older than N days |
| `HANDOFF_POLL_INTERVAL` | `5` | Watcher poll interval (seconds) |

The per-host HMAC key is auto-generated at `state/.envelope_key` (owner-only, 600) on first run. No configuration needed.

---

## How the human answers

Three paths, ranked by friction:

1. **Telegram reply** — bot DM contains question + buttons. Reply writes `answers/q_<id>.json` via bot webhook. **Lowest friction.**
2. **Web mini-UI** — `scripts/web_ui.py` (FastAPI, localhost only). Lists pending questions, form submit writes the JSON. (Phase 2 roadmap item.)
3. **Direct file edit** — open `answers/q_<id>.json` in editor, fill in `answers` field, save. **Always works.**

Answer schema:

```json
{
  "question_id": "q_<id>",
  "session_id": "<session_id from question file>",
  "parent_version": 1,
  "head_commit_at_answer": "<git rev-parse HEAD>",
  "answers": [{"answer": "your answer here"}]
}
```

---

## Verification

After wire-up, sanity-check:

```bash
# 1. Trigger a deferred question
claude -p "Ask me which CSS framework I prefer (React, Vue, Svelte)" --bare

# 2. Check question file
ls C:/AI/agent-handoff/questions/

# 3. Check notification arrived (phone / Slack / ntfy)

# 4. Write answer
# Edit answers/q_<id>.json

# 5. Watcher resumes session automatically (if running)
# Or manually: python C:/AI/agent-handoff/scripts/resume.py --session-id <id>
```

---

## Retention / cleanup

```bash
# Show disk usage and pending counts
python C:/AI/agent-handoff/scripts/cleanup.py --status

# Archive old consumed pairs (dry run first)
python C:/AI/agent-handoff/scripts/cleanup.py --archive --dry-run
python C:/AI/agent-handoff/scripts/cleanup.py --archive

# Hard delete (asks for confirmation)
python C:/AI/agent-handoff/scripts/cleanup.py --purge
```

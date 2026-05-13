# Integration guide

## Two modes — pick one per install

| Mode | Hook | Turn behavior | When to use |
|------|------|---------------|-------------|
| **block** | `pretool_ask_block.py` | Hook polls answer file in-place → same turn, same context | Short human delays (minutes); want continuity inside one tool call |
| **defer** | `pretool_ask.py` | Hook returns `defer` → turn ends → watcher launches `claude -p --resume` | Long delays (hours/days); free up the Claude process |

Block mode requires a generous hook timeout (`timeout: 7200` = 2 h) — the merge script sets this for you. Past timeout, block mode falls back to defer.

## Claude Code wiring

### Merge hooks (safe — never overwrites)

```bash
# Global, block mode (recommended for interactive-like behavior)
python C:/AI/agent-handoff/scripts/merge_settings.py --global --mode block

# Global, defer mode (end-turn + watcher resume)
python C:/AI/agent-handoff/scripts/merge_settings.py --global --mode defer

# Per-repo
python C:/AI/agent-handoff/scripts/merge_settings.py --target /path/to/repo --mode block

# Dry-run
python C:/AI/agent-handoff/scripts/merge_settings.py --global --mode block --dry-run
```

The script appends only entries whose `command` string is not already present — running it twice is idempotent. A `.bak` copy of the original is created before any write.

### Block-mode env config

| Var | Default | Meaning |
|-----|---------|---------|
| `HANDOFF_BLOCK_TIMEOUT` | `1800` | Seconds the hook polls before falling back to defer |
| `HANDOFF_BLOCK_POLL` | `2.0` | Poll interval seconds |

### Non-interactive scope

Defer mode works in `claude -p` mode (resumable). Block mode works in both interactive and `-p` — the hook simply blocks the tool call until answer arrives.

---

## Codex CLI wiring

### Merge hooks globally (safe — never overwrites)

```bash
python C:/AI/agent-handoff/scripts/merge_codex.py
# preview:
python C:/AI/agent-handoff/scripts/merge_codex.py --dry-run
```

Codex same-turn pause is not natively possible: the `Stop` hook fires *after* the turn ends, so handoff uses the `[[QUESTION:q_<id>]]` marker + `SessionStart` answer injection pattern (effectively defer-mode).

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

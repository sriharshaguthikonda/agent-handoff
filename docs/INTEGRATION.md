# Integration guide

## Claude Code wiring

### Per-project settings (recommended)

In the target repo, drop `.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "AskUserQuestion",
        "hooks": [
          {
            "type": "command",
            "command": "python C:/AI/agent-handoff/claude/pretool_ask.py"
          }
        ]
      }
    ],
    "Notification": [
      {
        "matcher": "permission_prompt|idle_prompt",
        "hooks": [
          {
            "type": "command",
            "command": "python C:/AI/agent-handoff/scripts/notify.py"
          }
        ]
      }
    ]
  }
}
```

### Global settings (all projects)

Append the same `hooks` block into `C:/Users/deletable/.claude/settings.json` (merge, don't overwrite).

### Non-interactive only

`defer` is documented to work in `claude -p` mode only. Interactive sessions cannot defer the same way. For interactive sessions, the hook falls back to writing the question file and notifying, but the session continues normally (user can still answer via the regular prompt). The handoff path is most valuable for long autonomous runs.

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

## Watcher daemon

`scripts/resume.py` runs as a background process. Options:

| OS | Mechanism |
|----|-----------|
| Windows | Scheduled Task (registered via PowerShell — see `scripts/install_watcher_windows.ps1`) |
| Linux | systemd user unit (`agent-handoff.service` + `.timer`) |
| macOS | launchd plist |

For now: run manually — `python C:/AI/agent-handoff/scripts/resume.py --watch`.

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

`notify.py` reads `.env` and fans out. Missing tokens skip silently — fan-out is best-effort.

## How the human answers

Three paths, ranked by friction:

1. **Telegram reply** — bot DM contains question + buttons. Reply writes `answers/q_<id>.json` via bot webhook. **Lowest friction.** (Phase 2.)
2. **Web mini-UI** — `scripts/web_ui.py` (FastAPI, localhost only). Lists pending questions, form submit writes the JSON. (Phase 2.)
3. **Direct file edit** — open `answers/q_<id>.json` in editor, fill in `answers` field, save. **Always works.**

## Verification

After wire-up, sanity-check by:

```bash
# 1. Trigger a deferred question in a Claude -p run
echo "Ask me which CSS framework I prefer (React, Vue, Svelte)" | claude -p

# 2. Check question file exists
ls C:/AI/agent-handoff/questions/

# 3. Check notification was sent (check phone / Slack / etc.)

# 4. Write answer manually
# edit answers/q_<id>.json

# 5. Resume
python C:/AI/agent-handoff/scripts/resume.py --session-id <id>
```

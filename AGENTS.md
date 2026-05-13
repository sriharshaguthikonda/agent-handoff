# Repo index — agent-handoff

File-based sleep/wake handshake so coding agents can ask humans questions without burning context on transcript replay. Cross-tool (Claude Code + Codex CLI). Local-first. Windows-primary, POSIX-friendly.

## Map

| Path | Purpose |
|------|---------|
| `README.md` | Vision + status |
| `docs/ARCHITECTURE.md` | Three-state model, JSON contracts, sleep/wake flow |
| `docs/INTEGRATION.md` | How to wire Claude + Codex hooks into a target repo |
| `docs/ROADMAP.md` | Phases 0-7 (all complete) |
| `docs/THREAT_MODEL.md` | (TBD — future) |
| `lib/core.py` | Shared logic: atomic I/O, question/answer contracts, HMAC signing, TTL, replay detection, lock |
| `claude/pretool_ask.py` | Claude `PreToolUse` defer/allow hook |
| `claude/settings.example.json` | Reference hook config (use `merge_settings.py` instead of copying) |
| `codex/stop_gate.py` | Codex `Stop` hook — detect `[[QUESTION:q_<id>]]` marker |
| `codex/session_start.py` | Codex `SessionStart` hook — inject answer |
| `codex/hooks.example.json` | Drop-in for `~/.codex/hooks.json` |
| `scripts/notify.py` | Fan-out to ntfy, Telegram, Slack, BurntToast |
| `scripts/resume.py` | Watcher + resume launcher |
| `scripts/merge_settings.py` | Safely merge hook config into an existing `.claude/settings.json` |
| `scripts/cleanup.py` | Archive or purge old question/answer pairs (Phase 7) |
| `scripts/install_watcher_windows.ps1` | Register Windows Scheduled Task (1-min poll) |
| `handoff/HANDOFF.{md,json}` | Canonical sleep state (gitignored runtime, template committed) |
| `questions/q_*.json` | Agent → human (runtime, gitignored) |
| `answers/q_*.json` | Human → agent (runtime, gitignored) |
| `answers/q_*.consumed.json` | Processed answers (gitignored) |
| `audit/events.jsonl` | Append-only audit (runtime, gitignored) |
| `state/` | Active session + provider state + envelope key (runtime, gitignored) |
| `archive/YYYY-MM/` | Archived old pairs (runtime, gitignored) |

## Conventions

- Atomic rename for every JSON write
- Owner-only file permissions on `answers/` and `state/.envelope_key`
- Notification payloads = `question_id + 1-line summary`. **Never** full prompt or tool output.
- Hooks run with full user privileges — validate every input, never `eval` model output, never accept paths from tool input.
- HMAC-SHA256 envelope on every question; per-host key auto-generated at `state/.envelope_key`
- Replay detection via audit log — same question_id cannot resume twice

## Current phase

All phases 0-7 complete. 65 tests green. See `docs/ROADMAP.md` for details.

## Quick start

```bash
# 1. Copy .env.example to .env and fill in tokens (Telegram, ntfy, etc.)

# 2. Wire hooks into target repo (SAFE — never overwrites)
python C:/AI/agent-handoff/scripts/merge_settings.py --target /path/to/your-repo
# or globally:
python C:/AI/agent-handoff/scripts/merge_settings.py --global

# 3. Install watcher as Windows Scheduled Task (runs every 60s)
powershell -ExecutionPolicy Bypass -File scripts/install_watcher_windows.ps1

# 4. Run a Claude non-interactive session
claude -p "do something that needs a human decision" --bare

# 5. Answer appears in questions/. Write answers/q_<id>.json:
#    {"question_id":"q_...","session_id":"...","parent_version":1,"head_commit_at_answer":"...","answers":[{"answer":"your answer"}]}
# Watcher detects it, resumes session automatically.

# 6. Cleanup old pairs (monthly)
python C:/AI/agent-handoff/scripts/cleanup.py --status
python C:/AI/agent-handoff/scripts/cleanup.py --archive
```

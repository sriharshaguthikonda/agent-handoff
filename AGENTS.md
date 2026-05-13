# Repo index — agent-handoff

File-based sleep/wake handshake so coding agents can ask humans questions without burning context on transcript replay. Cross-tool (Claude Code + Codex CLI). Local-first. Windows-primary, POSIX-friendly.

## Map

| Path | Purpose |
|------|---------|
| `README.md` | Vision + status |
| `docs/ARCHITECTURE.md` | Three-state model, JSON contracts, sleep/wake flow |
| `docs/INTEGRATION.md` | How to wire Claude + Codex hooks into a target repo |
| `docs/ROADMAP.md` | Phases 0-7 |
| `docs/THREAT_MODEL.md` | (TBD — Phase 4) |
| `claude/pretool_ask.py` | Claude `PreToolUse` defer/allow hook |
| `claude/settings.example.json` | Drop-in for `.claude/settings.json` |
| `codex/stop_gate.py` | Codex `Stop` hook — detect `[[QUESTION:q_<id>]]` marker |
| `codex/session_start.py` | Codex `SessionStart` hook — inject answer |
| `codex/hooks.example.json` | Drop-in for `~/.codex/hooks.json` |
| `scripts/notify.py` | Fan-out to ntfy, Telegram, Slack, BurntToast |
| `scripts/resume.py` | Watcher + resume launcher |
| `handoff/HANDOFF.{md,json}` | Canonical sleep state (gitignored runtime, template committed) |
| `questions/q_*.json` | Agent → human (runtime, gitignored) |
| `answers/q_*.json` | Human → agent (runtime, gitignored) |
| `audit/events.jsonl` | Append-only audit (runtime, gitignored) |
| `state/` | Active session + provider state (runtime, gitignored) |

## Conventions

- Atomic rename for every JSON write
- Owner-only file permissions on `answers/`
- Notification payloads = `question_id + 1-line summary`. **Never** full prompt or tool output.
- Hooks run with full user privileges — validate every input, never `eval` model output, never accept paths from tool input.

## Current phase

Phases 0-3 complete. 37 tests green. See `docs/ROADMAP.md` for Phase 4+ deliverables.

## Quick start

```bash
# 1. Copy .env.example to .env and fill in tokens
# 2. Wire Claude Code hook (copy claude/settings.example.json to .claude/settings.json in target repo)
# 3. Start watcher
python scripts/resume.py --watch

# 4. Run a Claude non-interactive session
claude -p "do something that needs a human decision" --bare

# 5. Answer appears in questions/. Write answers/q_<id>.json:
#    {"question_id":"q_...","session_id":"...","parent_version":1,"head_commit_at_answer":"...","answers":[{"answer":"your answer"}]}
# Watcher detects it, resumes session automatically.
```

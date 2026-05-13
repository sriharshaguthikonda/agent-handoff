# Roadmap

## Phase 0 — scaffold ✅ DONE
- Directory tree, design docs, `.gitignore`, `.env.example`, template HANDOFF.md

## Phase 1 — Claude E2E ✅ DONE
- `lib/core.py`: stable question_id, atomic JSON I/O, audit log, question/answer contracts, validation, HANDOFF state
- `claude/pretool_ask.py`: defer on no answer, allow+updatedInput on valid answer, stale rejection
- `scripts/resume.py`: watcher + one-shot resume, `claude -p --resume`, consumed-file rename
- 37 tests, all green

## Phase 2 — multi-channel notifier ✅ DONE (stdlib only)
- `scripts/notify.py`: ntfy + Telegram + Slack + BurntToast fan-out, ID-only payloads
- `scripts/install_watcher_windows.ps1`: Scheduled Task installer
- 9 notifier tests with mocked HTTP
- TODO future: Telegram bot webhook auto-writes `answers/q_<id>.json` on reply

## Phase 3 — Codex adapter ✅ DONE
- `codex/stop_gate.py`: `[[QUESTION:q_<id>]]` marker detection, question file + notify
- `codex/session_start.py`: inject unconsumed answer via `additionalContext`, consumed-file skip

## Phase 4 — integrity hardening
- Branch/commit drift detection on answer arrival
- Stale answer rejection (`HANDOFF_ANSWER_TTL`)
- Atomic rename helper (`scripts/_atomic.py`)
- Monotonic `HANDOFF.json` version with lock file

## Phase 5 — signed envelopes
- HMAC over `question_id + session_id + version + checksum`
- Per-host secret in `state/.envelope_key` (owner-only)
- Replay rejection via `audit/events.jsonl` lookup

## Phase 6 — tests + observability
- End-to-end integration test with `claude -p` mock (PTY or pipe)
- Resume validation edge cases (version race, TTL expiry)
- Disk usage cap + archival cron

## Phase 7 — retention + cleanup
- Cron job to archive answered `q_*.json` pairs older than N days into `archive/YYYY-MM/`
- Manual purge command
- Disk usage cap

## Out of scope (for now)
- Cloud-hosted handoff server (use OpenAI background mode or Copilot cloud agent)
- Multi-user / team handoff (single-user local-first)
- Cross-machine sync (use Syncthing on `answers/` if needed)

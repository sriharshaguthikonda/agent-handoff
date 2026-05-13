# Roadmap

## Phase 0 — scaffold ✅ DONE
- Directory tree, design docs, `.gitignore`, `.env.example`, template HANDOFF.md

## Phase 1 — Claude E2E ✅ DONE
- `lib/core.py`: stable question_id, atomic JSON I/O, audit log, question/answer contracts, validation, HANDOFF state
- `claude/pretool_ask.py`: defer on no answer, allow+updatedInput on valid answer, stale rejection
- `scripts/resume.py`: watcher + one-shot resume, `claude -p --resume`, consumed-file rename
- 19 core tests, 9 hook tests

## Phase 2 — multi-channel notifier ✅ DONE (stdlib only)
- `scripts/notify.py`: ntfy + Telegram + Slack + BurntToast fan-out, ID-only payloads
- `scripts/install_watcher_windows.ps1`: Scheduled Task installer (1-min poll, auto-start)
- 9 notifier tests with mocked HTTP

## Phase 3 — Codex adapter ✅ DONE
- `codex/stop_gate.py`: `[[QUESTION:q_<id>]]` marker detection, question file + notify
- `codex/session_start.py`: inject unconsumed answer via `additionalContext`, consumed-file skip

## Phase 4 — integrity hardening ✅ DONE
- `HANDOFF_ANSWER_TTL`: reject answers older than N seconds (configurable via `.env`)
- Replay detection: audit log scan blocks double-resume of same question
- `handoff_lock`: cross-platform file lock (O_EXCL) for HANDOFF.json monotonic version
- All checks wired into both `pretool_ask.py` and `resume.py` `process_answer` path

## Phase 5 — signed envelopes ✅ DONE
- HMAC-SHA256 over `question_id + session_id + version + checksum`
- Per-host secret auto-generated at `state/.envelope_key` (owner-only, 0600)
- `verify_question_sig` called on answer receipt — mismatched sig defers instead of allowing
- Backwards-compatible: old questions without `hmac_sig` skip verification

## Phase 6 — tests + observability ✅ DONE
- `tests/test_phase4.py`: 28 tests covering TTL, replay, lock, HMAC signing, edge cases
- Total: 65 tests, all green
- `scripts/cleanup.py --status`: disk usage and pending/answered counts

## Phase 7 — retention + cleanup ✅ DONE
- `scripts/cleanup.py --archive`: move old consumed pairs to `archive/YYYY-MM/`
- `scripts/cleanup.py --purge`: hard-delete with interactive confirmation
- `scripts/cleanup.py --status`: disk usage summary
- Retention window: `HANDOFF_RETENTION_DAYS` env var (default 30)

## Settings integration helper ✅ DONE
- `scripts/merge_settings.py`: safe merge into target repo's `.claude/settings.json`
  - Never overwrites — appends only missing entries
  - Backs up existing file before write
  - `--target`, `--global`, `--dry-run` flags

## Phase 8 — same-turn pause (block mode) ✅ DONE
- `claude/pretool_ask_block.py`: blocking variant — polls answer file in-place, returns `allow` when answer arrives. No session-end, no resume. Same turn, same context.
- Config: `HANDOFF_BLOCK_TIMEOUT` (default 1800s), `HANDOFF_BLOCK_POLL` (default 2.0s)
- `merge_settings.py --mode block`: wires the blocking hook with `timeout: 7200` (2 h Claude Code hook deadline)
- 3 new tests in `test_phase4.py::TestBlockingHook` (allow-on-existing-answer, defer-on-timeout, resolves-mid-poll)
- Backwards compatible: defer-mode (`pretool_ask.py`) untouched; choose per install via `--mode`

## Codex global merge ✅ DONE
- `scripts/merge_codex.py`: same safe-merge pattern for `~/.codex/hooks.json`
- Codex same-turn pause is not natively possible (Codex `Stop` hook fires *after* turn ends); Codex uses the established `[[QUESTION]]` marker + SessionStart-injection pattern → effectively defer-mode only

## Out of scope (for now)
- Cloud-hosted handoff server (use OpenAI background mode or Copilot cloud agent)
- Multi-user / team handoff (single-user local-first)
- Cross-machine sync (use Syncthing on `answers/` if needed)
- Telegram bot webhook auto-write on reply (future Phase 2 extension)
- Web mini-UI FastAPI localhost server (future Phase 2 extension)

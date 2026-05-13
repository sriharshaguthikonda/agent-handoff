# Roadmap

## Phase 0 — scaffold (DONE)
- Directory tree
- Data contract docs (`ARCHITECTURE.md`)
- Integration guide (`INTEGRATION.md`)
- Stub hook scripts (Claude + Codex)
- Stub notifier (multi-channel)
- Stub watcher (`resume.py`)
- `.gitignore`, `.env.example`

## Phase 1 — Claude E2E
- Real `claude/pretool_ask.py`:
  - Stable question_id derivation from `(session_id, turn_id, hash(tool_input))`
  - Atomic write of `questions/q_<id>.json` with version + checksum
  - Invoke `scripts/notify.py` with `QUESTION_ID` + `QUESTION_SUMMARY` env
  - Append audit event
  - Write `handoff/HANDOFF.md` + `HANDOFF.json` (single-writer locked)
- Real `resume.py --watch`:
  - Detect new answer, validate `parent_version` + `head_commit`
  - Invoke `claude -p --resume <sid>` with `--bare` reproducibility flag
- Test fixture: dummy `-p` run that calls `AskUserQuestion`, verify defer → file → resume → allow
- Install instructions for global Claude settings

## Phase 2 — multi-channel notifier polish
- Telegram bot: inline-keyboard reply writes `answers/q_<id>.json`
- Web mini-UI (FastAPI, localhost): list pending, form submit
- Rate limiting + dedup (don't fire 5 times if hook re-fires)
- Severity → channel mapping (blocking = SMS escalation after N min)

## Phase 3 — Codex adapter
- Real `codex/stop_gate.py`: write question file, notify, mark session paused in state
- Real `codex/session_start.py`: scan unconsumed answers for `session_id`, inject via `additionalContext`
- Prompt template for `AGENTS.md` insertion
- Limit: this still adds one turn — document the tradeoff

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
- `tests/test_pretool_ask.py` — hook contract round-trip
- `tests/test_stop_gate.py` — marker detection
- `tests/test_notify.py` — channel fan-out with mocked HTTP
- `tests/test_resume_validation.py` — version/commit drift cases
- Append-only `audit/events.jsonl` schema validator
- Optional: ingest audit events into `C:\.memory\` Postgres via `import_from_md.py`

## Phase 7 — retention + cleanup
- Cron job to archive answered `q_*.json` pairs older than N days into `archive/YYYY-MM/`
- Manual purge command
- Disk usage cap

## Out of scope (for now)
- Cloud-hosted handoff server (use OpenAI background mode or Copilot cloud agent if you need that)
- Multi-user / team handoff (single-user local-first)
- Cross-machine sync (use Syncthing on `answers/` if you must)

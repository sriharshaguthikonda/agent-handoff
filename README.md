# agent-handoff

**Goal**: kill exponential context blow-up from human-in-the-loop turns. Agent sleeps after asking a question, notifies user, user answers in a file, agent resumes the same session and reads only the delta answer — no transcript replay.

## Why

LLM-per-turn cost grows because every prior turn re-enters the prompt. Each clarifying back-and-forth multiplies tokens for both sides. Existing CLI agents have the primitives (Claude Code `defer`, Codex `Stop`/`SessionStart`, durable session IDs) but no shared workflow.

This system wires those primitives into one file-based handoff loop:

```
agent → write question file → notify user → SLEEP (same session)
                                                       ↓
user phone push → user writes answer file
                                                       ↓
agent wakes → reads answer → continues same session
```

No new turn. No transcript replay. Cost stays roughly linear instead of quadratic.

## Status

**Phase 0 — scaffold.** Layout + design docs only. No working hooks yet.

See `docs/ARCHITECTURE.md` for data contracts and `docs/INTEGRATION.md` for wire-up plan.

## Layout

```
agent-handoff/
  handoff/          canonical human + machine state
    HANDOFF.md
    HANDOFF.json
  questions/        q_<id>.json  written by agent
  answers/          q_<id>.json  written by human
  state/            session.json, provider_state.json
  audit/            events.jsonl (append-only)
  scripts/          notify.py, resume.py (provider-agnostic)
  claude/           Claude Code hook adapters
  codex/            Codex CLI hook adapters
  docs/             architecture, integration, threat model
  tests/            integration tests
```

## Design pillars (from research report `turns-context-reduction-deep-research-report.md`)

1. **Human-readable handoff** — `HANDOFF.md`
2. **Machine-readable queue** — `questions/` + `answers/` with versioning + branch/commit anchors
3. **Local checkpoint/transcript layer** — never reload full transcript into model context
4. **External notification leg** — independent of agent runtime (ntfy + Telegram + BurntToast + Slack fan-out)
5. **Resume command** — `claude -p --resume <session>` or `codex resume <session>`

## Provider matrix

| Provider | Mechanism | Maturity |
|----------|-----------|----------|
| Claude Code | `PreToolUse` hook on `AskUserQuestion` → `permissionDecision: "defer"` → resume with `updatedInput` | Native, documented. **Primary target.** |
| Codex CLI | `Stop` hook detects `[[QUESTION:q_<id>]]` marker → write file → notify → `SessionStart` injects answer via `additionalContext` on `codex resume` | Workaround. Several `PreToolUse` fields parsed-but-not-supported. |

## Integration with existing systems on this machine

- **`C:\.memory\` (PostgreSQL + pgvector memory)** — handoff is **not** memory. Audit events (`audit/events.jsonl`) can be ingested into memory via `import_from_md.py` post-hoc, but the handoff system itself stays file-local for speed and isolation.
- **Active rescue plan (`ok-let-s-get-this-silly-pond.md`)** — already mentions Telegram review. Reuse that bot token for notification leg (see `.env.example`).
- **CLAUDE.md global preferences** — Windows-ready bash, local-first tools, terse output. Respected throughout.

## Next phases

- **Phase 1** — Claude adapter E2E (`PreToolUse` defer + Notification hook + `resume.py`)
- **Phase 2** — multi-channel notifier with ID-only payloads (no secret leak)
- **Phase 3** — Codex adapter via Stop marker convention
- **Phase 4** — branch/commit drift checks + stale-answer rejection
- **Phase 5** — signed envelopes (HMAC) + replay protection
- **Phase 6** — tests + observability + retention policy

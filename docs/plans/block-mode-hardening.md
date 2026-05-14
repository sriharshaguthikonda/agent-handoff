# Block-mode hardening plan

Handoff for next agent. Three independent workstreams. Each is small enough
for a one-PR change. Do them in any order; merge_settings change is the only
one that requires re-running the global install.

## Background

As of commits `402b924` (telegram ingest) + `6535dbe` (timeout bump) + manual
settings dedupe (2026-05-14), block mode end-to-end is verified working:

```
q_720489bf3738cb22 / q_ed03293bf890f31c (audit/events.jsonl):
  question_created -> block_wait_started -> telegram_answer_written
  -> session_resumed (mode:block) -> block_wait_resolved -> answer_accepted
```

Two cosmetic + UX issues remain. They are not crashes — they cause noise,
wasted spawns, or invisible-wait UX.

---

## Workstream A — watcher must skip block-mode questions

**Symptom.** Audit log shows the watcher firing `resume_dispatched` after
`block_wait_resolved` for the same question_id, immediately followed by
`answer_replay_blocked`. The block-mode hook handled the answer in the same
turn; the watcher then spawned a redundant `claude -p --resume <session>`
that the replay guard kills 5s later.

**Why it matters.** Wasted process spawn (cold-cache Claude session), wasted
notification fan-out potential, confusing audit trail, possible race if
replay guard ever regresses.

**Root cause.** `questions/q_<id>.json` does not carry a `mode` field, so
`scripts/resume.py::process_answer` cannot tell defer-mode from block-mode
answers. It treats every new answer as a defer-mode resume trigger.

**Fix.**

1. `lib/core.py::write_question` — add `mode: str = "defer"` parameter,
   persist `question["mode"] = mode` in the JSON payload.
2. `claude/pretool_ask_block.py` — pass `mode="block"` to `write_question`.
3. `claude/pretool_ask.py` — leave call as-is (defaults to `"defer"`),
   or pass `mode="defer"` explicitly for clarity.
4. `scripts/resume.py::process_answer` — after loading the question,
   skip + log if `question.get("mode") == "block"`:

   ```python
   if question.get("mode") == "block":
       append_audit("answer_skipped", question_id=question_id, reason="block_mode_in_session")
       _mark_consumed(root, question_id)
       return
   ```

5. Tests:
   - `test_phase4.py` or new `test_resume_skips_block.py`: write a
     block-mode question + answer, run `process_answer`, assert no
     `resume_dispatched` event, assert `answer_skipped` event with reason
     `block_mode_in_session`, assert answer file renamed to `.consumed.json`.
   - Keep existing defer-mode resume test passing.

**Out of scope.** Don't try to detect block-mode by scanning audit for
`session_resumed` — fragile and racy. The `mode` field is the source of
truth.

**Backwards compat.** Existing question files without `mode` field default
to `"defer"` via `.get("mode") != "block"` — old answers keep resuming.

---

## Workstream B — `merge_settings.py` should prune the opposite mode

**Symptom.** Running `merge_settings.py --global --mode defer` then later
`--mode block` (or vice-versa) leaves BOTH hook entries in
`~/.claude/settings.json` because the append-only merger only checks
exact command-string match. Both hooks fire on every `AskUserQuestion`,
producing duplicate `question_created` audit events and ambiguous turn
behavior (defer hook returns `defer` immediately while block hook is
still polling).

We hit this on 2026-05-13 and had to manually dedupe (see commit history
around `6535dbe`).

**Fix.**

1. In `scripts/merge_settings.py::merge_into`, BEFORE calling
   `merge_hooks`, prune any existing `AskUserQuestion` entry whose
   command points at the OPPOSITE mode's script:
   - When `_MODE == "block"`: drop any entry containing
     `claude/pretool_ask.py` (not `pretool_ask_block.py`).
   - When `_MODE == "defer"`: drop any entry containing
     `claude/pretool_ask_block.py`.
2. Match by substring on the command string. Be careful: `pretool_ask.py`
   is a suffix of `pretool_ask_block.py`, so test for `_block.py` first.
3. Log the prune to stdout so the user knows: `pruned -> PreToolUse/AskUserQuestion (defer-mode hook replaced by block)`.
4. Tests:
   - New `tests/test_merge_settings.py` (file does not exist yet) with three
     cases:
     - Fresh install with no AskUserQuestion entry: behaves as today.
     - Existing defer entry + `--mode block`: defer entry pruned, block
       entry added, exactly one matcher remains.
     - Existing block entry + `--mode defer`: block entry pruned.
   - Use `tmp_path` for the target settings.json and pass via `--target`.

**Out of scope.** Don't touch other matchers. Don't touch
`Notification` hooks. The prune is scoped to `PreToolUse` /
`AskUserQuestion` only.

---

## Workstream C — same-turn wait visibility (UX)

**User feedback (2026-05-14).** User watched a Codex bash tool show
`6m37s · 5.8k tokens` while polling and stayed comfortable. With the
block-mode hook, Claude Code shows nothing — no progress, no elapsed,
no "still waiting on telegram reply" signal. User perceives this as
"crash for some reason".

This is purely a UX gap, not a correctness bug. Existing block hook works,
just feels dead.

**Options (pick one — discuss with user first).**

### C.1 — Heartbeat audit + statusline pull

- pretool_ask_block.py emits a `block_wait_heartbeat` audit event every
  N seconds (default 30s) with `elapsed`, `question_id`, `summary`.
- User's existing statusline (`statusline-handoff.ps1`) reads
  `state/active_session.json` + last audit line to render
  `waiting on q_<id>: 4m12s · telegram`.
- Pros: no Claude Code surface change, leverages statusline.
- Cons: only visible in interactive sessions, statusline-handoff.ps1
  lives outside this repo so coordination needed.

### C.2 — Periodic stderr emission

- Hook writes `still waiting (elapsed=Xs)` to stderr every 60s.
- Claude Code may or may not surface hook stderr in the UI; verify
  before committing.

### C.3 — Notification re-fan-out at midpoint

- At `HANDOFF_BLOCK_TIMEOUT / 2`, fire a second Telegram nudge:
  "still waiting on q_<id>".
- Pros: pulls user attention back to phone.
- Cons: spammy; cap at 1 nudge per question.

**Recommended.** Start with C.1 (heartbeat audit + statusline). Lowest
risk, no behavioral change, and the statusline already exists. If user
wants phone-push reminders, layer C.3 on top with a config flag.

**Out of scope.** Don't add a Claude Code progress bar. The hook is a
black-box subprocess and CC doesn't expose progress callbacks.

---

## Acceptance for the whole batch

- 77 -> ≥80 tests still green (`python -m pytest tests/ -q`).
- One `question_created` event per question (not two). Verify by
  running an `AskUserQuestion` and tailing `audit/events.jsonl`.
- No `resume_dispatched` event after `block_wait_resolved` for a
  block-mode question.
- `merge_settings.py --global --mode <other>` cleanly replaces the
  installed mode.
- (If C.1 picked) `block_wait_heartbeat` events visible in audit log
  every ~30s during a real wait.

## Don't touch

- `lib/core.py` HMAC/TTL/replay code — phase 4-5 hardening, working.
- Codex side. Codex `Stop` hook fires after the turn ends, so same-turn
  pause is architecturally impossible there. Don't waste time.
- `scripts/notify.py` outbound format — Telegram force-reply already
  works; only touch if implementing C.3.
- The retired duplicate defer-hook entry in `~/.claude/settings.json` is
  already manually removed (2026-05-14). Backup at
  `~/.claude/settings.json.bak.<ts>`. Workstream B prevents it
  re-appearing.

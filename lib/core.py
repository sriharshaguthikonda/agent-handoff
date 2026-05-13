"""Shared core logic for agent-handoff.

All file I/O is atomic via os.replace(tmp → final).
All public helpers are pure-Python stdlib — no third-party deps.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Root discovery
# ---------------------------------------------------------------------------

def find_root() -> Path:
    """Walk up from this file's parent until we find the repo root (.gitignore).

    Tests can inject a temp dir via HANDOFF_ROOT_OVERRIDE env var.
    """
    override = os.environ.get("HANDOFF_ROOT_OVERRIDE")
    if override:
        return Path(override)
    here = Path(__file__).resolve().parent
    for candidate in [here, here.parent, here.parent.parent]:
        if (candidate / ".gitignore").exists() and (candidate / "claude").exists():
            return candidate
    return here.parent  # fallback


HANDOFF_ROOT = find_root()


# ---------------------------------------------------------------------------
# .env loader (stdlib only)
# ---------------------------------------------------------------------------

def load_env(root: Path | None = None) -> dict[str, str]:
    root = root or HANDOFF_ROOT
    env: dict[str, str] = {}
    env_path = root / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    # os.environ wins over .env
    env.update(os.environ)
    return env


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def get_git_info(repo_path: str | Path | None = None) -> dict[str, str]:
    cwd = str(repo_path) if repo_path else None
    out: dict[str, str] = {"branch": "unknown", "commit": "unknown"}
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=cwd, stderr=subprocess.DEVNULL, timeout=5
        ).decode().strip()
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd, stderr=subprocess.DEVNULL, timeout=5
        ).decode().strip()
        out["commit"] = commit
        out["branch"] = branch
    except Exception:
        pass
    return out


# ---------------------------------------------------------------------------
# question_id derivation — stable across hook re-fires
# ---------------------------------------------------------------------------

def derive_question_id(session_id: str, tool_input: dict) -> str:
    body_hash = hashlib.sha256(
        json.dumps(tool_input, sort_keys=True).encode("utf-8")
    ).hexdigest()[:8]
    sid = (session_id or "nosid")[:6]
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"q_{ts}_{sid}_{body_hash}"


def derive_question_id_stable(session_id: str, tool_input: dict) -> str:
    """Deterministic — same session+body always → same ID.

    Used when re-checking if a question was already written for this deferred call.
    (Timestamp-free so it survives hook re-fires on resume.)
    """
    raw = f"{session_id}:{json.dumps(tool_input, sort_keys=True)}"
    return "q_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Atomic JSON I/O
# ---------------------------------------------------------------------------

def atomic_write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".tmp", dir=path.parent, delete=False, encoding="utf-8"
    ) as f:
        json.dump(obj, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
        tmp = f.name
    os.replace(tmp, str(path))


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

def append_audit(event_type: str, root: Path | None = None, **kwargs: Any) -> None:
    root = root or HANDOFF_ROOT
    audit_path = root / "audit" / "events.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event_type,
        **kwargs,
    }
    with open(str(audit_path), "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


# ---------------------------------------------------------------------------
# Question file
# ---------------------------------------------------------------------------

def write_question(
    root: Path,
    question_id: str,
    session_id: str,
    provider: str,
    tool_input: dict,
    repo: str = "",
    fallback_policy: str = "block_until_answer",
) -> Path:
    git = get_git_info(repo or None)
    questions = tool_input.get("questions") or []
    summary = questions[0].get("question", "") if questions else ""

    obj: dict = {
        "question_id": question_id,
        "session_id": session_id,
        "provider": provider,
        "tool": "AskUserQuestion",
        "repo": repo,
        "branch": git["branch"],
        "head_commit": git["commit"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "waiting_for_human",
        "severity": "blocking",
        "fallback_policy": fallback_policy,
        "questions": questions,
        "context_summary": summary,
        "version": 1,
    }
    # checksum over content without checksum key
    obj["checksum"] = "sha256:" + hashlib.sha256(
        json.dumps({k: v for k, v in obj.items() if k != "checksum"}, sort_keys=True).encode()
    ).hexdigest()

    path = root / "questions" / f"{question_id}.json"
    atomic_write_json(path, obj)
    return path


def read_question(root: Path, question_id: str) -> dict | None:
    return read_json(root / "questions" / f"{question_id}.json")


# ---------------------------------------------------------------------------
# Answer file
# ---------------------------------------------------------------------------

def read_answer(root: Path, question_id: str) -> dict | None:
    return read_json(root / "answers" / f"{question_id}.json")


def validate_answer(question: dict, answer: dict) -> tuple[bool, str]:
    """Return (ok, reason). Reject stale / mismatched answers."""
    if answer.get("question_id") != question.get("question_id"):
        return False, "question_id mismatch"
    if answer.get("parent_version", 0) < question.get("version", 1):
        return False, f"answer parent_version {answer.get('parent_version')} < question version {question.get('version')}"
    q_commit = question.get("head_commit", "unknown")
    a_commit = answer.get("head_commit_at_answer", "unknown")
    if q_commit != "unknown" and a_commit != "unknown" and q_commit != a_commit:
        policy = question.get("fallback_policy", "block_until_answer")
        if policy == "abandon_if_stale_after_head_change":
            return False, f"repo drifted: question={q_commit[:8]}, answer={a_commit[:8]}"
        # default: warn but accept
    return True, "ok"


# ---------------------------------------------------------------------------
# HANDOFF state files
# ---------------------------------------------------------------------------

def write_handoff_state(
    root: Path,
    question_id: str,
    session_id: str,
    provider: str,
    status: str = "waiting_for_human",
    repo: str = "",
) -> None:
    git = get_git_info(repo or None)
    obj = {
        "version": _next_handoff_version(root),
        "active_session": {
            "provider": provider,
            "session_id": session_id,
            "repo": repo,
            "branch": git["branch"],
            "head_commit": git["commit"],
            "status": status,
            "blocking_question_id": question_id,
        },
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    atomic_write_json(root / "handoff" / "HANDOFF.json", obj)

    q = read_question(root, question_id)
    summary = q.get("context_summary", "") if q else ""
    md = (
        f"# Handoff state\n\n"
        f"**Status**: {status}\n"
        f"**Question**: {question_id}\n"
        f"**Session**: {session_id} ({provider})\n"
        f"**Branch**: {git['branch']} @ `{git['commit'][:8]}`\n"
        f"**Summary**: {summary}\n\n"
        f"Write your answer to `answers/{question_id}.json`, then `resume.py --session-id {session_id}` fires automatically.\n\n"
        f"Updated: {datetime.now(timezone.utc).isoformat()}\n"
    )
    (root / "handoff" / "HANDOFF.md").write_text(md, encoding="utf-8")


def _next_handoff_version(root: Path) -> int:
    existing = read_json(root / "handoff" / "HANDOFF.json")
    if existing:
        return existing.get("version", 0) + 1
    return 1


# ---------------------------------------------------------------------------
# Active session state
# ---------------------------------------------------------------------------

def save_active_session(root: Path, session_id: str, provider: str, question_id: str) -> None:
    atomic_write_json(root / "state" / "active_session.json", {
        "session_id": session_id,
        "provider": provider,
        "question_id": question_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })


def load_active_session(root: Path) -> dict | None:
    return read_json(root / "state" / "active_session.json")

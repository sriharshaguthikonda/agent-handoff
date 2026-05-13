#!/usr/bin/env python3
"""Provider-agnostic notification fan-out.

Reads NOTIFY_TARGETS env and dispatches to enabled channels.
Payload carries question_id + short summary ONLY. Never raw prompts or secrets.

PHASE 0 STUB. Real urllib/requests calls land in Phase 2.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

HANDOFF_ROOT = Path(__file__).resolve().parent.parent


def load_env() -> dict[str, str]:
    env_path = HANDOFF_ROOT / ".env"
    out = dict(os.environ)
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            out.setdefault(k.strip(), v.strip())
    return out


def send_ntfy(env: dict, payload: dict) -> bool:
    url = env.get("NTFY_URL", "").strip()
    if not url or "REPLACE-ME" in url:
        return False
    req = urllib.request.Request(
        url,
        data=payload["summary"].encode("utf-8"),
        headers={"Title": f"Agent blocked: {payload['question_id']}"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=5).read()
        return True
    except Exception as e:
        print(f"ntfy failed: {e}", file=sys.stderr)
        return False


def send_telegram(env: dict, payload: dict) -> bool:
    token = env.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = env.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = json.dumps({
        "chat_id": chat,
        "text": f"Agent blocked: {payload['question_id']}\n{payload['summary']}",
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=5).read()
        return True
    except Exception as e:
        print(f"telegram failed: {e}", file=sys.stderr)
        return False


def send_slack(env: dict, payload: dict) -> bool:
    url = env.get("SLACK_WEBHOOK_URL", "").strip()
    if not url:
        return False
    body = json.dumps({"text": f"{payload['question_id']}: {payload['summary']}"}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=5).read()
        return True
    except Exception as e:
        print(f"slack failed: {e}", file=sys.stderr)
        return False


def send_burnttoast(env: dict, payload: dict) -> bool:
    if env.get("BURNTTOAST_ENABLED", "0") != "1":
        return False
    ps = (
        "Import-Module BurntToast -ErrorAction SilentlyContinue; "
        f"New-BurntToastNotification -Text 'Agent blocked', '{payload['question_id']}: {payload['summary']}'"
    )
    try:
        subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps], timeout=10, check=False)
        return True
    except Exception as e:
        print(f"burnttoast failed: {e}", file=sys.stderr)
        return False


CHANNELS = {
    "ntfy": send_ntfy,
    "telegram": send_telegram,
    "slack": send_slack,
    "burnttoast": send_burnttoast,
}


def main() -> int:
    env = load_env()

    # Hook-mode: read JSON from stdin and build payload
    payload = {
        "question_id": env.get("QUESTION_ID", "unknown"),
        "summary": env.get("QUESTION_SUMMARY", "Agent needs input"),
    }
    try:
        data = sys.stdin.read()
        if data:
            evt = json.loads(data)
            payload["question_id"] = evt.get("question_id", payload["question_id"])
            payload["summary"] = evt.get("message") or evt.get("summary") or payload["summary"]
    except Exception:
        pass

    targets = [t.strip() for t in env.get("NOTIFY_TARGETS", "ntfy").split(",") if t.strip()]
    results = {}
    for t in targets:
        fn = CHANNELS.get(t)
        if not fn:
            continue
        results[t] = fn(env, payload)

    print(json.dumps({"notify_results": results}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

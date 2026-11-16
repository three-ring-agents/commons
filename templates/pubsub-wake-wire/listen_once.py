#!/usr/bin/env python3
"""
listen_once.py — Cloud/Local Reactive Wake Wire via GCP Pub/Sub REST Pull
=========================================================================
Part of `dont-tell-the-wifi` Phase 5 (Machine Wake Wire).
When launched as a background command in an Antigravity Cloud Remote Conversation
(`run_command` with `WaitMsBeforeAsync`), it polls a shared GCP Pub/Sub subscription
via REST, acknowledges the first received message, prints the JSON payload to stdout,
and exits 0 — immediately triggering Antigravity's reactive background-task wakeup!
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

STATE_DIR = Path(os.environ.get("ANTIGRAVITY_STATE_DIR", str(Path.home() / ".gemini" / "state")))
CONFIG_PATH = STATE_DIR / "config.json"
DEFAULT_PUBSUB_PROJECT = "{{PUBSUB_PROJECT_ID}}"


def resolve_pubsub_defaults() -> tuple[str, str]:
    """Read parameterized `pubsub.project_id` and `pubsub.subscription_id` from `~/.gemini/state/config.json`."""
    project_id = (os.environ.get("GCHAT_PUBSUB_PROJECT") or DEFAULT_PUBSUB_PROJECT).strip()
    subscription_id = (os.environ.get("GCHAT_PUBSUB_SUBSCRIPTION") or "").strip()
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            pubsub_cfg = cfg.get("pubsub") or {}
            if pubsub_cfg.get("project_id"):
                project_id = str(pubsub_cfg["project_id"]).strip()
            if not subscription_id and pubsub_cfg.get("subscription_id"):
                subscription_id = str(pubsub_cfg["subscription_id"]).strip()
            if not subscription_id and cfg.get("operator"):
                op = str(cfg["operator"]).strip().lower()
                if op and not op.startswith("<"):
                    subscription_id = f"sub-{op}"
        except Exception:
            pass
    return project_id, subscription_id


def load_access_token() -> Optional[str]:
    """
    Resolve a bearer token in priority order:
    1. Explicit `GOOGLE_OAUTH_ACCESS_TOKEN` or `PUBSUB_BEARER_TOKEN` env var.
    2. `~/.config/gcloud/application_default_credentials.json` (`refresh_token` exchange via stdlib `urllib`).
    3. `gcloud auth print-access-token` CLI fallback (zero secret files needed when direct `@gmail.com` IAM is bound).
    """
    import subprocess
    import urllib.parse

    env_tok = os.environ.get("GOOGLE_OAUTH_ACCESS_TOKEN") or os.environ.get("PUBSUB_BEARER_TOKEN")
    if env_tok:
        return env_tok.strip()

    adc_path = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
    if adc_path.exists():
        try:
            adc = json.loads(adc_path.read_text(encoding="utf-8"))
            if adc.get("refresh_token") and adc.get("client_id") and adc.get("client_secret"):
                form = urllib.parse.urlencode(
                    {
                        "client_id": adc["client_id"],
                        "client_secret": adc["client_secret"],
                        "refresh_token": adc["refresh_token"],
                        "grant_type": "refresh_token",
                    }
                ).encode("utf-8")
                req = urllib.request.Request(
                    "https://oauth2.googleapis.com/token",
                    data=form,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    tok = json.loads(resp.read().decode("utf-8")).get("access_token", "")
                if tok:
                    return str(tok).strip()
        except Exception:
            pass

    for cmd in (["gcloud", "auth", "print-access-token"], ["gcloud", "auth", "application-default", "print-access-token"]):
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10, shell=False, check=False)
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip()
        except Exception:
            continue
    return None


def pull_once(project_id: str, subscription_id: str, token: str, timeout_sec: int = 300) -> int:
    sub_path = f"projects/{project_id}/subscriptions/{subscription_id}"
    pull_url = f"https://pubsub.googleapis.com/v1/{sub_path}:pull"
    ack_url = f"https://pubsub.googleapis.com/v1/{sub_path}:acknowledge"

    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        req = urllib.request.Request(
            pull_url,
            data=json.dumps({"maxMessages": 1}).encode("utf-8"),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                body: Dict[str, Any] = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            sys.stderr.write(f"Pub/Sub poll warning: {exc}\n")
            time.sleep(5)
            continue

        messages = body.get("receivedMessages") or []
        if messages:
            msg = messages[0]
            ack_id = msg.get("ackId")
            raw_b64 = (msg.get("message") or {}).get("data", "")
            decoded = base64.b64decode(raw_b64).decode("utf-8", errors="replace") if raw_b64 else "{}"

            if ack_id:
                ack_req = urllib.request.Request(
                    ack_url,
                    data=json.dumps({"ackIds": [ack_id]}).encode("utf-8"),
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    method="POST",
                )
                try:
                    urllib.request.urlopen(ack_req, timeout=10).read()
                except Exception:
                    pass

            print(
                json.dumps(
                    {
                        "event": "PUBSUB_WAKE_WIRE_MESSAGE",
                        "subscription": sub_path,
                        "messageId": (msg.get("message") or {}).get("messageId"),
                        "attributes": (msg.get("message") or {}).get("attributes", {}),
                        "payload": decoded,
                    },
                    indent=2,
                )
            )
            return 0
        time.sleep(2)

    print(json.dumps({"event": "PUBSUB_TIMEOUT_NO_MESSAGES", "subscription": sub_path}))
    return 0


def main() -> int:
    default_proj, default_sub = resolve_pubsub_defaults()
    parser = argparse.ArgumentParser(description="Single-shot GCP Pub/Sub wake wire listener for Antigravity agents")
    parser.add_argument(
        "--project",
        default=default_proj,
        help="GCP Project ID hosting the shared Pub/Sub topic (defaults to config.json pubsub.project_id or {{PUBSUB_PROJECT_ID}})",
    )
    parser.add_argument(
        "--subscription",
        default=default_sub,
        required=not bool(default_sub),
        help="Subscription name (defaults to config.json pubsub.subscription_id or sub-<operator>)",
    )
    parser.add_argument("--timeout", type=int, default=300, help="Max poll duration in seconds before clean exit")
    args = parser.parse_args()

    token = load_access_token()
    if not token:
        sys.stderr.write(
            "No PUBSUB_BEARER_TOKEN / GOOGLE_OAUTH_ACCESS_TOKEN or gcloud ADC available yet. "
            "Run `gcloud auth application-default login` to authorize Zero-Key Pub/Sub access.\n"
        )
        return 1

    return pull_once(args.project, args.subscription, token, args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())

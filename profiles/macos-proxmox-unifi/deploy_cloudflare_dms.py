#!/usr/bin/env python3
"""
Zero-Dependency Cloudflare Worker + KV + Cron Trigger Dead-Man's Switch Provisioner & Heartbeat Client
Playbook: profiles/macos-proxmox-unifi/deploy_cloudflare_dms.py

Uses pure Python stdlib (`urllib.request`, `hmac`, `hashlib`, `secrets`) against the Cloudflare v4 API
(zero `npx`/`wrangler` 3P dependencies).

Required Cloudflare API Token Permissions:
  - Account -> Workers KV Storage -> Edit
  - Account -> Workers Scripts -> Edit
  - Zone -> Workers Routes -> Edit
  - Zone -> DNS -> Edit
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import secrets
import ssl
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "{{CLOUDFLARE_ACCOUNT_ID}}")
ZONE_ID = os.environ.get("CLOUDFLARE_ZONE_ID", "{{CLOUDFLARE_ZONE_ID}}")
DMS_HOSTNAME = os.environ.get("DMS_HOSTNAME", "{{DMS_HOSTNAME}}")
EXTERNAL_PROBE_URL = os.environ.get("EXTERNAL_PROBE_URL", "https://{{EXTERNAL_TUNNEL_HOST}}")
SCRIPT_NAME = "agy-dead-mans-switch"
KV_TITLE = "AGY_DMS_KV"

BASE_DIR = Path(__file__).resolve().parent
WORKER_JS_PATH = BASE_DIR / "cloudflare_worker_dead_mans_switch.js"
STATE_DIR = Path.home() / ".gemini" / "state"
CONFIG_PATH = STATE_DIR / "cloudflare_dms_config.json"

_SSL_CTX = ssl.create_default_context()


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_str = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    tmp_path = Path(tmp_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def _load_or_init_config() -> dict[str, Any]:
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("hmac_secret"):
                return data
        except (OSError, json.JSONDecodeError):
            pass
    cfg = {
        "account_id": ACCOUNT_ID,
        "zone_id": ZONE_ID,
        "script_name": SCRIPT_NAME,
        "endpoint_url": f"https://{DMS_HOSTNAME}/v1/heartbeat",
        "status_url": f"https://{DMS_HOSTNAME}/v1/status",
        "hmac_secret": secrets.token_hex(32),
        "monitored_hosts": "mac-mini,proxmox-pve",
        "stale_threshold_seconds": "900",
        "external_probe_url": EXTERNAL_PROBE_URL,
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    _atomic_write_json(CONFIG_PATH, cfg)
    return cfg


def _cf_api(
    method: str,
    path: str,
    token: str,
    body: bytes | dict[str, Any] | list[Any] | None = None,
    content_type: str = "application/json",
) -> tuple[int, dict[str, Any]]:
    url = f"https://api.cloudflare.com/client/v4{path}"
    raw_bytes: bytes | None = None
    if isinstance(body, (dict, list)):
        raw_bytes = json.dumps(body).encode("utf-8")
    elif isinstance(body, bytes):
        raw_bytes = body
    req = urllib.request.Request(
        url,
        data=raw_bytes,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": content_type,
            "Accept": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=20, context=_SSL_CTX) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        err_raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(err_raw)
        except json.JSONDecodeError:
            return exc.code, {"success": False, "raw_error": err_raw}


def deploy_worker(token: str) -> dict[str, Any]:
    cfg = _load_or_init_config()
    diag: dict[str, Any] = {"config_path": str(CONFIG_PATH)}

    # 1. Ensure KV Namespace exists
    code_kv, obj_kv = _cf_api("GET", f"/accounts/{ACCOUNT_ID}/storage/kv/namespaces?per_page=50", token)
    diag["kv_list_http"] = code_kv
    if code_kv != 200:
        diag["status"] = "NEEDS_WORKERS_TOKEN_SCOPE"
        return diag

    kv_id = ""
    for ns in obj_kv.get("result") or []:
        if isinstance(ns, dict) and ns.get("title") == KV_TITLE:
            kv_id = str(ns.get("id") or "")
            break
    if not kv_id:
        code_create, obj_create = _cf_api(
            "POST",
            f"/accounts/{ACCOUNT_ID}/storage/kv/namespaces",
            token,
            {"title": KV_TITLE},
        )
        diag["kv_create_http"] = code_create
        if code_create in (200, 201):
            kv_id = str((obj_create.get("result") or {}).get("id") or "")
    if not kv_id:
        diag["status"] = "ERROR_KV"
        return diag

    cfg["kv_namespace_id"] = kv_id
    _atomic_write_json(CONFIG_PATH, cfg)

    # 2. Upload ES Module Worker via multipart/form-data
    boundary = f"----AGYWorkerBoundary{secrets.token_hex(8)}"
    metadata = {
        "main_module": "worker.js",
        "compatibility_date": "2026-01-01",
        "bindings": [
            {"type": "kv_namespace", "name": "DMS_KV", "namespace_id": kv_id},
            {"type": "secret_text", "name": "DMS_HMAC_SECRET", "text": cfg["hmac_secret"]},
            {"type": "plain_text", "name": "MONITORED_HOSTS", "text": cfg["monitored_hosts"]},
            {"type": "plain_text", "name": "STALE_THRESHOLD_SECONDS", "text": cfg["stale_threshold_seconds"]},
            {"type": "plain_text", "name": "EXTERNAL_PROBE_URL", "text": cfg["external_probe_url"]},
        ],
    }
    js_code = WORKER_JS_PATH.read_text(encoding="utf-8")
    parts = [
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="metadata"; filename="metadata.json"\r\n'
        "Content-Type: application/json\r\n\r\n"
        f"{json.dumps(metadata)}\r\n",
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="worker.js"; filename="worker.js"\r\n'
        "Content-Type: application/javascript+module\r\n\r\n"
        f"{js_code}\r\n"
        f"--{boundary}--\r\n",
    ]
    code_w, _ = _cf_api(
        "PUT",
        f"/accounts/{ACCOUNT_ID}/workers/scripts/{SCRIPT_NAME}",
        token,
        body="".join(parts).encode("utf-8"),
        content_type=f"multipart/form-data; boundary={boundary}",
    )
    diag["worker_upload_http"] = code_w

    # 3. Attach 5-minute Cron Trigger (*/5 * * * *)
    code_cron, _ = _cf_api(
        "PUT",
        f"/accounts/{ACCOUNT_ID}/workers/scripts/{SCRIPT_NAME}/schedules",
        token,
        body=[{"cron": "*/5 * * * *"}],
    )
    diag["cron_schedule_http"] = code_cron
    diag["status"] = "DEPLOYED"
    return diag


def push_heartbeat(host: str = "mac-mini", storagekitd_threads: int = 0, sre_slo_ok: bool = True) -> dict[str, Any]:
    cfg = _load_or_init_config()
    secret = str(cfg.get("hmac_secret") or "")
    endpoint = str(cfg.get("endpoint_url") or f"https://{DMS_HOSTNAME}/v1/heartbeat")
    now_sec = str(int(time.time()))
    payload_str = json.dumps(
        {
            "host": host,
            "storagekitd_threads": storagekitd_threads,
            "sre_slo_ok": sre_slo_ok,
            "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    sig = hmac.new(
        secret.encode("utf-8"),
        f"{now_sec}.{payload_str}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    req = urllib.request.Request(
        endpoint,
        data=payload_str.encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-DMS-Timestamp": now_sec,
            "X-DMS-Signature": sig,
            "User-Agent": "AGY-DMS-Pusher/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10, context=_SSL_CTX) as resp:
        return {"status": "OK", "http": resp.status, "response": json.loads(resp.read().decode("utf-8"))}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["deploy", "push-heartbeat"], default="push-heartbeat")
    parser.add_argument("--host", default="mac-mini")
    args = parser.parse_args()
    if args.action == "deploy":
        print(json.dumps(deploy_worker(os.environ["CLOUDFLARE_API_TOKEN"]), indent=2))
    else:
        print(json.dumps(push_heartbeat(host=args.host), indent=2))

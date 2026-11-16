#!/usr/bin/env python3
"""
gchat.py — Direct Google Chat CLI for Antigravity (Cloud Remote VMs & Local Hosts)
===================================================================================
Supports:
  1. `status`: Inspect configured Google Chat rooms (`humans`, `backchannel`, etc.) in
     private `~/.gemini/state/config.json` and OAuth / Bearer / Webhook readiness.
  2. `auth-login`: Run Google Chat OAuth 2.0 flow (`chat.spaces`, `chat.messages`,
     `chat.memberships`, with `access_type=offline` & `prompt=select_account consent`)
     using local loopback (`127.0.0.1:8765`) or headless `--no-browser` / `--code` paste,
     saving a persistent auto-refreshing `refresh_token` in `~/.gemini/state/gchat_oauth.json` (0600).
  3. `create-space`: Programmatically create an external-capable Google Chat space via
     `POST https://chat.googleapis.com/v1/spaces:setup` (omitting `externalUserAllowed`
     when authenticated as a consumer `@gmail.com` user per Google's `v1.spaces` schema)
     and invite initial members in a single atomic API call.
  4. `set-webhook`: Save a Google Chat Incoming Webhook URL (or `op://` pointer) and
     extracted `spaces/<SPACE_ID>` into private `~/.gemini/state/config.json`.
  5. `post`: Post plain text, threaded messages (`threadKey`), or Google Chat Cards v2
     directly to `https://chat.googleapis.com/v1/spaces/.../messages` via auto-refreshed
     OAuth Bearer token or Incoming Webhook. Works through `agy-plugin-proxy` on Cloud VMs and locally.
  6. `list-messages`: Read recent messages from a Google Chat space via
     `GET https://chat.googleapis.com/v1/spaces/{space_id}/messages`.
  7. `--self-test`: Deterministic verification tests.
"""

from __future__ import annotations

import argparse
import base64
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

STATE_DIR = Path(os.environ.get("ANTIGRAVITY_STATE_DIR", str(Path.home() / ".gemini" / "state")))
MESH_DIR = Path(os.environ.get("ANTIGRAVITY_MESH_DIR", str(Path.home() / ".gemini" / "mesh")))
CONFIG_PATH = STATE_DIR / "config.json"
MESH_CONFIG_PATH = MESH_DIR / "mesh.json"
OAUTH_TOKEN_PATH = STATE_DIR / "gchat_oauth.json"
AGENT_OAUTH_TOKEN_PATH = STATE_DIR / "gchat_agent_oauth.json"


def _load_ring2_mesh_defaults() -> Tuple[Dict[str, str], str, str]:
    spaces = {
        "humans": "spaces/{{GCHAT_HUMANS_SPACE_ID}}",
        "backchannel": "spaces/{{GCHAT_BACKCHANNEL_SPACE_ID}}",
    }
    proj = "{{PUBSUB_PROJECT_ID}}"
    topic = "{{PUBSUB_TOPIC_ID}}"
    if MESH_CONFIG_PATH.exists():
        try:
            m = json.loads(MESH_CONFIG_PATH.read_text(encoding="utf-8"))
            g_rooms = m.get("gchat_rooms") or {}
            if (g_rooms.get("humans") or {}).get("space_id"):
                spaces["humans"] = str(g_rooms["humans"]["space_id"])
            if (g_rooms.get("backchannel") or {}).get("space_id"):
                spaces["backchannel"] = str(g_rooms["backchannel"]["space_id"])
            ps = m.get("pubsub") or {}
            if ps.get("project_id"):
                proj = str(ps["project_id"])
            if ps.get("topic_id"):
                topic = str(ps["topic_id"])
        except Exception:
            pass
    return spaces, proj, topic


DEFAULT_SPACE_IDS, DEFAULT_PUBSUB_PROJECT, DEFAULT_PUBSUB_TOPIC = _load_ring2_mesh_defaults()

CHAT_OAUTH_SCOPES: List[str] = [
    "https://www.googleapis.com/auth/chat.spaces",
    "https://www.googleapis.com/auth/chat.messages",
    "https://www.googleapis.com/auth/chat.memberships",
]

_SPACE_ID_RE = re.compile(r"(spaces/[A-Za-z0-9_-]+)")


def resolve_op_uri(val: str) -> str:
    """
    Resolve a secret URI pointer at runtime without hardcoding plaintext in config.json.
    Supports:
      - `op://Agent-<User>/Item/Field` (1Password CLI)
      - `keychain://service/account` (macOS Keychain via `/usr/bin/security`)
      - `secret-tool://service/account` (Linux libsecret via `secret-tool`)
      - `file://~/.gemini/state/...` (Local 0600 secret file)
      - `env://VAR_NAME` (Environment variable)
    """
    if not isinstance(val, str) or not val:
        return val
    if val.startswith("env://"):
        env_key = val[len("env://") :].strip()
        return os.environ.get(env_key, "").strip() or val
    if val.startswith("file://"):
        raw_p = val[len("file://") :].strip()
        p = Path(raw_p).expanduser()
        if p.exists():
            try:
                return p.read_text(encoding="utf-8").strip()
            except Exception:
                return val
        return val
    if val.startswith("keychain://"):
        parts = val[len("keychain://") :].strip("/").split("/", 1)
        if len(parts) == 2 and Path("/usr/bin/security").exists():
            try:
                res = subprocess.run(
                    ["/usr/bin/security", "find-generic-password", "-s", parts[0], "-a", parts[1], "-w"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                if res.returncode == 0 and res.stdout.strip():
                    return res.stdout.strip()
            except Exception:
                pass
        return val
    if val.startswith("secret-tool://"):
        parts = val[len("secret-tool://") :].strip("/").split("/", 1)
        st_bin = shutil.which("secret-tool")
        if len(parts) == 2 and st_bin:
            try:
                res = subprocess.run(
                    [st_bin, "lookup", "service", parts[0], "account", parts[1]],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                if res.returncode == 0 and res.stdout.strip():
                    return res.stdout.strip()
            except Exception:
                pass
        return val
    if not val.startswith("op://"):
        return val
    op_bin = shutil.which("op")
    if not op_bin and (Path.home() / ".local" / "bin" / "op").exists():
        op_bin = str(Path.home() / ".local" / "bin" / "op")
    if not op_bin:
        return val
    try:
        res = subprocess.run([op_bin, "read", val], capture_output=True, text=True, timeout=10, check=False)
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return val


def load_json_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_json_atomic_0600(data: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    fd, tmp_path = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=str(path.parent))
    try:
        try:
            os.fchmod(fd, 0o600)
        except OSError:
            pass
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(data, indent=2) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, str(path))
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise


def load_state_config(path: Path = CONFIG_PATH) -> Dict[str, Any]:
    return load_json_file(path)


def save_state_config(cfg: Dict[str, Any], path: Path = CONFIG_PATH) -> None:
    save_json_atomic_0600(cfg, path)


def extract_space_id(url_or_id: str) -> str:
    m = _SPACE_ID_RE.search(url_or_id or "")
    if m:
        return m.group(1)
    cleaned = (url_or_id or "").strip()
    if cleaned and not cleaned.startswith("http") and not cleaned.startswith("op://"):
        return cleaned if cleaned.startswith("spaces/") else f"spaces/{cleaned}"
    return ""


def parse_oauth_client_config(raw: Dict[str, Any]) -> Tuple[str, str, str]:
    """Extract (client_id, client_secret, token_uri) from installed/web or flat OAuth JSON."""
    block = raw.get("installed") or raw.get("web") or raw
    client_id = str(block.get("client_id") or "").strip()
    client_secret = str(block.get("client_secret") or "").strip()
    token_uri = str(block.get("token_uri") or "https://oauth2.googleapis.com/token").strip()
    return client_id, client_secret, token_uri


def refresh_oauth_access_token(
    client_id: str,
    client_secret: str,
    refresh_token: str,
    token_uri: str = "https://oauth2.googleapis.com/token",
) -> Tuple[Optional[str], int]:
    """Exchange an OAuth 2.0 refresh_token for a fresh access_token."""
    form = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        token_uri,
        data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            access_token = body.get("access_token")
            expires_in = int(body.get("expires_in", 3600))
            if access_token:
                return str(access_token), int(time.time()) + expires_in
    except Exception:
        pass
    return None, 0


def resolve_bearer_token(cfg: Dict[str, Any], r_cfg: Dict[str, Any], oauth_path: Path = OAUTH_TOKEN_PATH) -> Tuple[Optional[str], str]:
    """
    Return (bearer_token, source_description).
    Order of precedence:
      1. GCHAT_BEARER_TOKEN env var
      2. Auto-refreshing OAuth credentials in ~/.gemini/state/gchat_oauth.json or secrets.gchat_oauth_json
      3. Room or global gchat_bearer_token in config.json
    """
    env_tok = (os.environ.get("GCHAT_BEARER_TOKEN") or "").strip()
    if env_tok:
        return env_tok, "GCHAT_BEARER_TOKEN env var"

    oauth_data = load_json_file(oauth_path)
    if not oauth_data:
        secrets = cfg.get("secrets") or {}
        raw_oauth_ptr = secrets.get("gchat_oauth_json", "")
        resolved_oauth_str = resolve_op_uri(raw_oauth_ptr) if raw_oauth_ptr else ""
        if resolved_oauth_str and not resolved_oauth_str.startswith("op://"):
            try:
                oauth_data = json.loads(resolved_oauth_str)
            except Exception:
                oauth_data = {}

    if oauth_data:
        now = int(time.time())
        cached_access = str(oauth_data.get("access_token") or "").strip()
        expiry = int(oauth_data.get("expiry_epoch") or 0)
        if cached_access and expiry > now + 60:
            return cached_access, f"OAuth token ({oauth_path.name}, valid)"

        client_id, client_secret, token_uri = parse_oauth_client_config(oauth_data)
        refresh_tok = str(oauth_data.get("refresh_token") or "").strip()
        if client_id and client_secret and refresh_tok:
            new_access, new_expiry = refresh_oauth_access_token(client_id, client_secret, refresh_tok, token_uri)
            if new_access:
                oauth_data["access_token"] = new_access
                oauth_data["expiry_epoch"] = new_expiry
                try:
                    save_json_atomic_0600(oauth_data, oauth_path)
                except Exception:
                    pass
                return new_access, f"OAuth refresh_token ({oauth_path.name}, auto-refreshed)"

    secrets = cfg.get("secrets") or {}
    raw_token = r_cfg.get("bearer_token") or secrets.get("gchat_bearer_token") or ""
    resolved_token = resolve_op_uri(raw_token) if raw_token else None
    if resolved_token and not resolved_token.startswith("op://"):
        return resolved_token, "config.json bearer_token"

    return None, "unconfigured"


def resolve_agent_bearer_token(
    cfg: Dict[str, Any],
    r_cfg: Dict[str, Any],
    agent_oauth_path: Path = AGENT_OAUTH_TOKEN_PATH,
) -> Tuple[Optional[str], str]:
    """
    Resolve a dedicated Agent-seat Google Chat OAuth token (`--send-as agent` direct mode).
    Checks:
      1. GCHAT_AGENT_BEARER_TOKEN env var
      2. ~/.gemini/state/gchat_agent_oauth.json or secrets.gchat_agent_oauth_json
      3. secrets.gchat_agent_bearer_token in config.json
    """
    env_tok = (os.environ.get("GCHAT_AGENT_BEARER_TOKEN") or "").strip()
    if env_tok:
        return env_tok, "GCHAT_AGENT_BEARER_TOKEN env var"

    oauth_data = load_json_file(agent_oauth_path)
    if not oauth_data:
        secrets = cfg.get("secrets") or {}
        raw_oauth_ptr = secrets.get("gchat_agent_oauth_json", "")
        resolved_oauth_str = resolve_op_uri(raw_oauth_ptr) if raw_oauth_ptr else ""
        if resolved_oauth_str and not resolved_oauth_str.startswith("op://"):
            try:
                oauth_data = json.loads(resolved_oauth_str)
            except Exception:
                oauth_data = {}

    if oauth_data:
        now = int(time.time())
        cached_access = str(oauth_data.get("access_token") or "").strip()
        expiry = int(oauth_data.get("expiry_epoch") or 0)
        if cached_access and expiry > now + 60:
            return cached_access, f"Agent OAuth token ({agent_oauth_path.name}, valid)"

        client_id, client_secret, token_uri = parse_oauth_client_config(oauth_data)
        refresh_tok = str(oauth_data.get("refresh_token") or "").strip()
        if client_id and client_secret and refresh_tok:
            new_access, new_expiry = refresh_oauth_access_token(client_id, client_secret, refresh_tok, token_uri)
            if new_access:
                oauth_data["access_token"] = new_access
                oauth_data["expiry_epoch"] = new_expiry
                try:
                    save_json_atomic_0600(oauth_data, agent_oauth_path)
                except Exception:
                    pass
                return new_access, f"Agent OAuth refresh_token ({agent_oauth_path.name}, auto-refreshed)"

    secrets = cfg.get("secrets") or {}
    raw_token = r_cfg.get("agent_bearer_token") or secrets.get("gchat_agent_bearer_token") or ""
    resolved_token = resolve_op_uri(raw_token) if raw_token else None
    if resolved_token and not resolved_token.startswith("op://"):
        return resolved_token, "config.json gchat_agent_bearer_token"

    return None, "unconfigured"


def resolve_pubsub_adc_bearer_token(cfg: Optional[Dict[str, Any]] = None) -> Tuple[Optional[str], str]:
    """
    Resolve a Zero-Key Google Cloud ADC / gcloud OAuth token for publishing to `{{PUBSUB_TOPIC_ID}}`.
    Order of precedence:
      1. PUBSUB_BEARER_TOKEN or GOOGLE_OAUTH_ACCESS_TOKEN env var
      2. ~/.config/gcloud/application_default_credentials.json (stdlib refresh_token exchange)
      3. `gcloud auth print-access-token` / `gcloud auth application-default print-access-token`
    """
    env_tok = (os.environ.get("PUBSUB_BEARER_TOKEN") or os.environ.get("GOOGLE_OAUTH_ACCESS_TOKEN") or "").strip()
    if env_tok:
        return env_tok, "PUBSUB_BEARER_TOKEN env var"

    adc_path = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
    if adc_path.exists():
        try:
            adc = json.loads(adc_path.read_text(encoding="utf-8"))
            if adc.get("refresh_token") and adc.get("client_id") and adc.get("client_secret"):
                tok, _ = refresh_oauth_access_token(
                    str(adc["client_id"]),
                    str(adc["client_secret"]),
                    str(adc["refresh_token"]),
                )
                if tok:
                    return tok, "gcloud ADC (~/.config/gcloud/application_default_credentials.json)"
        except Exception:
            pass

    for cmd in (["gcloud", "auth", "print-access-token"], ["gcloud", "auth", "application-default", "print-access-token"]):
        if not shutil.which(cmd[0]):
            continue
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10, shell=False, check=False)
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip(), f"`{' '.join(cmd)}`"
        except Exception:
            continue

    return None, "unconfigured"


def build_pubsub_relay_envelope(
    operator: str,
    room: str,
    space_id: str,
    text: str,
    thread_key: Optional[str] = None,
    card_title: Optional[str] = None,
    card_subtitle: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the `gchat_relay_post` event payload published to `{{PUBSUB_TOPIC_ID}}`."""
    return {
        "event": "gchat_relay_post",
        "sender": operator.strip().lower() or "unknown",
        "send_as": "agent",
        "room": room,
        "space_id": space_id,
        "thread_key": thread_key,
        "text": text,
        "card_title": card_title,
        "card_subtitle": card_subtitle,
        "timestamp": int(time.time()),
    }


def resolve_pubsub_target(cfg: Dict[str, Any]) -> Tuple[str, str]:
    """Resolve parameterized `(project_id, topic_id)` from env or `config.json` (`pubsub.*`)."""
    pubsub_cfg = cfg.get("pubsub") or {}
    project_id = str(
        os.environ.get("GCHAT_PUBSUB_PROJECT")
        or pubsub_cfg.get("project_id")
        or DEFAULT_PUBSUB_PROJECT
    ).strip()
    topic_id = str(
        os.environ.get("GCHAT_PUBSUB_TOPIC")
        or pubsub_cfg.get("topic_id")
        or DEFAULT_PUBSUB_TOPIC
    ).strip()
    return project_id, topic_id


def publish_gchat_relay_via_pubsub(
    cfg: Dict[str, Any],
    envelope: Dict[str, Any],
    pubsub_token: str,
) -> Tuple[bool, str]:
    """Publish a `gchat_relay_post` envelope to `projects/<pubsub.project_id>/topics/<pubsub.topic_id>`."""
    project_id, topic_id = resolve_pubsub_target(cfg)
    url = f"https://pubsub.googleapis.com/v1/projects/{project_id}/topics/{topic_id}:publish"
    encoded_data = base64.b64encode(json.dumps(envelope).encode("utf-8")).decode("ascii")
    body = {
        "messages": [
            {
                "data": encoded_data,
                "attributes": {
                    "event": "gchat_relay_post",
                    "sender": str(envelope.get("sender") or "unknown"),
                    "room": str(envelope.get("room") or "humans"),
                    "space_id": str(envelope.get("space_id") or ""),
                },
            }
        ]
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {pubsub_token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp_json = json.loads(resp.read().decode("utf-8"))
            msg_ids = resp_json.get("messageIds") or []
            msg_id = msg_ids[0] if msg_ids else "ok"
            return True, f"projects/{project_id}/topics/{topic_id} (messageId={msg_id})"
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        return False, f"Pub/Sub HTTP {exc.code}: {err_body}"
    except Exception as exc:
        return False, f"Pub/Sub error: {exc}"


def build_spaces_setup_payload(
    display_name: str,
    invite_emails: Optional[List[str]] = None,
    workspace_owned_external_flag: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Build a `POST /v1/spaces:setup` request body.
    Note: Per Google's `v1.spaces` spec, consumer `@gmail.com` accounts must OMIT
    `externalUserAllowed` (Google defaults consumer-created spaces to `externalUserAllowed: true`
    and rejects requests that explicitly set the field when authenticated as `@gmail.com`).
    """
    space_obj: Dict[str, Any] = {
        "spaceType": "SPACE",
        "displayName": display_name,
    }
    if workspace_owned_external_flag is not None:
        space_obj["externalUserAllowed"] = bool(workspace_owned_external_flag)

    memberships = []
    for email in invite_emails or []:
        clean_email = email.strip()
        if clean_email:
            memberships.append(
                {
                    "member": {
                        "name": f"users/{clean_email}",
                        "type": "HUMAN",
                    }
                }
            )
    payload: Dict[str, Any] = {"space": space_obj}
    if memberships:
        payload["memberships"] = memberships
    return payload


def build_message_payload(
    text: str,
    operator: str = "andrew",
    as_agent: bool = True,
    card_title: Optional[str] = None,
    card_subtitle: Optional[str] = None,
) -> Dict[str, Any]:
    op_display = operator.strip().capitalize() or "Operator"
    prefix = f"*[{op_display}'s Agent on behalf of {op_display}]*\n" if as_agent and not text.startswith("*[") else ""
    formatted_text = f"{prefix}{text}"

    payload: Dict[str, Any] = {"text": formatted_text}
    if card_title:
        payload["cardsV2"] = [
            {
                "cardId": "agy-agent-card",
                "card": {
                    "header": {
                        "title": card_title,
                        "subtitle": card_subtitle or f"{op_display}'s Antigravity Agent",
                    },
                    "sections": [
                        {
                            "widgets": [
                                {
                                    "textParagraph": {
                                        "text": text,
                                    }
                                }
                            ]
                        }
                    ],
                },
            }
        ]
    return payload


def append_thread_query_params(webhook_url: str, thread_key: Optional[str]) -> str:
    if not thread_key:
        return webhook_url
    parsed = urllib.parse.urlsplit(webhook_url)
    q = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    keys = {k for k, _ in q}
    if "threadKey" not in keys:
        q.append(("threadKey", thread_key))
    if "messageReplyOption" not in keys:
        q.append(("messageReplyOption", "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"))
    new_query = urllib.parse.urlencode(q)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, new_query, parsed.fragment))


def get_room_config(cfg: Dict[str, Any], room: str, oauth_path: Path = OAUTH_TOKEN_PATH) -> Tuple[str, str, Optional[str]]:
    """Return (resolved_webhook_url, space_id, resolved_bearer_token) for a logical room."""
    rooms = cfg.get("gchat_rooms") or {}
    r_cfg = rooms.get(room) or {}
    raw_webhook = r_cfg.get("webhook_url", "")
    resolved_webhook = resolve_op_uri(raw_webhook) if raw_webhook else ""
    space_id = r_cfg.get("space_id") or extract_space_id(resolved_webhook) or DEFAULT_SPACE_IDS.get(room, "")

    resolved_token, _ = resolve_bearer_token(cfg, r_cfg, oauth_path=oauth_path)
    return resolved_webhook, space_id, resolved_token


def cmd_status(
    cfg_path: Path = CONFIG_PATH,
    oauth_path: Path = OAUTH_TOKEN_PATH,
    agent_oauth_path: Path = AGENT_OAUTH_TOKEN_PATH,
) -> int:
    cfg = load_state_config(cfg_path)
    operator = cfg.get("operator", "unknown")
    rooms = dict(cfg.get("gchat_rooms") or {})
    for default_room, default_space in DEFAULT_SPACE_IDS.items():
        rooms.setdefault(default_room, {"space_id": default_space, "webhook_url": ""})
    human_token, human_src = resolve_bearer_token(cfg, {}, oauth_path=oauth_path)
    agent_token, agent_src = resolve_agent_bearer_token(cfg, {}, agent_oauth_path=agent_oauth_path)
    pubsub_token, pubsub_src = resolve_pubsub_adc_bearer_token(cfg)

    if agent_token:
        mode1_status = f"READY — Direct Agent OAuth Seat ({agent_src})"
    elif pubsub_token:
        mode1_status = f"READY — Zero-Key Pub/Sub Agent Relay (`{{PUBSUB_TOPIC_ID}}` via {pubsub_src})"
    elif human_token:
        mode1_status = f"READY — Fallback to Personal OAuth with `*[Agent]*` prefix ({human_src})"
    else:
        mode1_status = "NEEDS AUTH (run `gcloud auth application-default login` or `gchat.py auth-login`)"

    mode2_status = (
        f"READY — Personal `@gmail.com` OAuth ({human_src})"
        if human_token
        else "NEEDS AUTH (run `gchat.py auth-login` with External Desktop OAuth Client)"
    )

    print("=== Antigravity Google Chat (/gchat) Dual-Identity Status ===")
    print(f"Operator:                   {operator}")
    print(f"Config Path:                {cfg_path}")
    print(f"Mode 1 (--send-as agent):   {mode1_status}")
    print(f"Mode 2 (--send-as human):   {mode2_status}")
    print("\nConfigured Rooms:")
    for room_name, r_info in sorted(rooms.items()):
        raw_url = r_info.get("webhook_url", "")
        space_id = r_info.get("space_id") or extract_space_id(raw_url) or DEFAULT_SPACE_IDS.get(room_name, "(pending)")
        if raw_url.startswith("op://"):
            state = f"1Password pointer ({raw_url})"
        elif raw_url.startswith("https://chat.googleapis.com/"):
            state = "Direct Webhook URL configured (ready)"
        elif agent_token or pubsub_token or human_token:
            state = "Dual-Identity READY"
        else:
            state = "Awaiting `gcloud auth application-default login` or `gchat.py auth-login`"
        print(f"  • #{room_name:<18} space={space_id:<22} mode={state}")
    return 0


def extract_code_from_input(code_or_url: str) -> str:
    cleaned = code_or_url.strip()
    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        parsed = urllib.parse.urlsplit(cleaned)
        qs = urllib.parse.parse_qs(parsed.query)
        if "code" in qs and qs["code"]:
            return qs["code"][0].strip()
    return cleaned


def cmd_auth_login(
    client_secrets_path: Optional[str] = None,
    client_id_arg: Optional[str] = None,
    client_secret_arg: Optional[str] = None,
    port: int = 8765,
    no_browser: bool = False,
    auth_code: Optional[str] = None,
    oauth_path: Path = OAUTH_TOKEN_PATH,
) -> int:
    existing = load_json_file(oauth_path)
    client_id, client_secret, token_uri = parse_oauth_client_config(existing)

    if not client_id or not client_secret:
        cfg = load_state_config()
        secrets = cfg.get("secrets") or {}
        raw_oauth_ptr = secrets.get("gchat_oauth_json", "")
        resolved_oauth_str = resolve_op_uri(raw_oauth_ptr) if raw_oauth_ptr else ""
        if resolved_oauth_str and not resolved_oauth_str.startswith("op://"):
            try:
                cid, csec, turi = parse_oauth_client_config(json.loads(resolved_oauth_str))
                if cid and csec:
                    client_id, client_secret, token_uri = cid, csec, turi
            except Exception:
                pass
        if not client_id:
            op_cid = resolve_op_uri(str(secrets.get("gchat_oauth_client_id") or ""))
            if op_cid and not op_cid.startswith("op://"):
                client_id = op_cid.strip()
        if not client_secret:
            op_csec = resolve_op_uri(str(secrets.get("gchat_oauth_client_secret") or ""))
            if op_csec and not op_csec.startswith("op://"):
                client_secret = op_csec.strip()

    if client_secrets_path:
        raw = load_json_file(Path(client_secrets_path).expanduser())
        cid, csec, turi = parse_oauth_client_config(raw)
        if cid and csec:
            client_id, client_secret, token_uri = cid, csec, turi

    if client_id_arg:
        client_id = client_id_arg.strip()
    if client_secret_arg:
        client_secret = client_secret_arg.strip()

    if not client_id or not client_secret:
        sys.stderr.write(
            "OAuth client credentials required. Pass `--client-secrets /path/to/client_secret.json` "
            "or `--client-id <ID> --client-secret <SECRET>`.\n"
        )
        return 1

    redirect_uri = f"http://127.0.0.1:{port}"
    auth_params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(CHAT_OAUTH_SCOPES),
        "access_type": "offline",
        "prompt": "select_account consent",
    }
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(auth_params)}"

    code = extract_code_from_input(auth_code) if auth_code else ""
    if not code:
        if no_browser:
            print("=== Google Chat OAuth 2.0 Authorization (Headless / Cloud VM Mode) ===")
            print("1. Open this URL in your browser and select your Google account:")
            print(f"\n   {auth_url}\n")
            print("2. After approving, your browser will redirect to http://127.0.0.1:8765/?code=...")
            print("   Copy the full redirected URL (or the `code=` value) and re-run with `--code '<URL_OR_CODE>'`")
            try:
                if sys.stdin.isatty():
                    pasted = input("\nOr paste the redirected URL / code here now: ").strip()
                    code = extract_code_from_input(pasted)
            except EOFError:
                pass
            if not code:
                save_json_atomic_0600(
                    {"client_id": client_id, "client_secret": client_secret, "token_uri": token_uri},
                    oauth_path,
                )
                return 0
        else:
            captured: Dict[str, str] = {}

            class _CallbackHandler(http.server.BaseHTTPRequestHandler):
                def do_GET(self) -> None:  # noqa: N802
                    qs = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                    if "code" in qs:
                        captured["code"] = qs["code"][0]
                        body = b"<html><body><h2>Antigravity Google Chat OAuth Complete!</h2><p>You can close this tab and return to the terminal.</p></body></html>"
                        self.send_response(200)
                    else:
                        captured["error"] = qs.get("error", ["unknown"])[0]
                        body = b"<html><body><h2>OAuth Error</h2></body></html>"
                        self.send_response(400)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

                def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                    return

            server = http.server.HTTPServer(("127.0.0.1", port), _CallbackHandler)
            print(f"Opening browser for Google Chat OAuth consent (listening on {redirect_uri})...")
            print(f"Auth URL: {auth_url}")
            webbrowser.open(auth_url)
            server.handle_request()
            server.server_close()
            if "error" in captured:
                sys.stderr.write(f"OAuth authorization failed: {captured['error']}\n")
                return 1
            code = captured.get("code", "")

    if not code:
        sys.stderr.write("No authorization code received.\n")
        return 1

    token_form = urllib.parse.urlencode(
        {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        token_uri,
        data=token_form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            token_resp = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        sys.stderr.write(f"OAuth token exchange error ({exc.code}): {err_body}\n")
        return 1

    access_token = token_resp.get("access_token", "")
    refresh_token = token_resp.get("refresh_token") or existing.get("refresh_token", "")
    expires_in = int(token_resp.get("expires_in", 3600))
    saved_payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "token_uri": token_uri,
        "refresh_token": refresh_token,
        "access_token": access_token,
        "expiry_epoch": int(time.time()) + expires_in,
        "scopes": CHAT_OAUTH_SCOPES,
    }
    save_json_atomic_0600(saved_payload, oauth_path)
    print(f"✓ Saved auto-refreshing Google Chat OAuth credentials to {oauth_path} (mode 0600)")
    return 0


def cmd_set_webhook(room: str, url: str, space_id: Optional[str] = None, cfg_path: Path = CONFIG_PATH) -> int:
    cfg = load_state_config(cfg_path)
    rooms = cfg.setdefault("gchat_rooms", {})
    detected_space = space_id or extract_space_id(url) or DEFAULT_SPACE_IDS.get(room, "")
    rooms[room] = {
        "webhook_url": url.strip(),
        "space_id": detected_space,
    }
    save_state_config(cfg, cfg_path)
    print(f"✓ Saved Google Chat room '#{room}' in private {cfg_path} (space_id={detected_space or 'via-webhook'})")
    return 0


def cmd_create_space(
    room: str,
    display_name: str,
    invite_emails: Optional[List[str]] = None,
    dry_run: bool = False,
    cfg_path: Path = CONFIG_PATH,
) -> int:
    cfg = load_state_config(cfg_path)
    _, _, bearer_token = get_room_config(cfg, room)
    payload = build_spaces_setup_payload(display_name=display_name, invite_emails=invite_emails)
    if dry_run:
        print(json.dumps({"room": room, "endpoint": "https://chat.googleapis.com/v1/spaces:setup", "payload": payload}, indent=2))
        return 0
    if not bearer_token:
        sys.stderr.write(
            f"Creating space '{display_name}' requires a Google Chat OAuth bearer token (`chat.spaces`). "
            f"Run `gchat.py auth-login` or set `GCHAT_BEARER_TOKEN`.\n"
        )
        return 1

    req = urllib.request.Request(
        "https://chat.googleapis.com/v1/spaces:setup",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {bearer_token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            space_name = body.get("name", "")
            space_uri = body.get("spaceUri", "")
            rooms = cfg.setdefault("gchat_rooms", {})
            rooms.setdefault(room, {})["space_id"] = space_name
            save_state_config(cfg, cfg_path)
            print(f"✓ Created space '{display_name}' -> {space_name} ({space_uri})")
            return 0
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        sys.stderr.write(f"Google Chat API error ({exc.code}): {err_body}\n")
        return 1


def cmd_post(
    room: str,
    text: str,
    thread_key: Optional[str] = None,
    card_title: Optional[str] = None,
    card_subtitle: Optional[str] = None,
    send_as: str = "agent",
    via: str = "auto",
    dry_run: bool = False,
    cfg_path: Path = CONFIG_PATH,
    oauth_path: Path = OAUTH_TOKEN_PATH,
    agent_oauth_path: Path = AGENT_OAUTH_TOKEN_PATH,
) -> int:
    cfg = load_state_config(cfg_path)
    operator = str(cfg.get("operator", "andrew"))
    rooms = cfg.get("gchat_rooms") or {}
    r_cfg = rooms.get(room) or {}
    webhook_url, space_id, human_bearer_token = get_room_config(cfg, room, oauth_path=oauth_path)
    agent_bearer_token, _ = resolve_agent_bearer_token(cfg, r_cfg, agent_oauth_path=agent_oauth_path)

    normalized_send_as = (send_as or "agent").strip().lower()
    if normalized_send_as not in ("agent", "human"):
        sys.stderr.write(f"Invalid `--send-as {send_as}` (must be 'agent' or 'human').\n")
        return 1

    as_agent = normalized_send_as == "agent"
    payload = build_message_payload(
        text=text,
        operator=operator,
        as_agent=as_agent,
        card_title=card_title,
        card_subtitle=card_subtitle,
    )
    relay_envelope = build_pubsub_relay_envelope(
        operator=operator,
        room=room,
        space_id=space_id,
        text=text,
        thread_key=thread_key,
        card_title=card_title,
        card_subtitle=card_subtitle,
    )

    if dry_run:
        out: Dict[str, Any] = {
            "room": room,
            "space_id": space_id,
            "send_as": normalized_send_as,
            "via": via,
            "thread_key": thread_key,
            "payload": payload,
        }
        if as_agent:
            out["pubsub_relay_envelope"] = relay_envelope
        print(json.dumps(out, indent=2))
        return 0

    # Mode 2: Send as Human (Impersonate Human via personal @gmail.com OAuth token)
    if normalized_send_as == "human":
        if not space_id or not human_bearer_token:
            sys.stderr.write(
                f"Mode 2 (`--send-as human`) in '#{room}' ({space_id}) requires your personal `@gmail.com` "
                f"Google Chat OAuth token in {oauth_path}.\n"
                f"Run `gchat.py auth-login` once against the External Desktop OAuth Client, or use "
                f"`--send-as agent` (default) to post via the Zero-Key Pub/Sub Agent Relay.\n"
            )
            return 1
        base_url = f"https://chat.googleapis.com/v1/{space_id}/messages"
        target_url = append_thread_query_params(base_url, thread_key)
        headers = {
            "Content-Type": "application/json; charset=UTF-8",
            "Authorization": f"Bearer {human_bearer_token}",
        }
        req = urllib.request.Request(
            target_url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                msg_name = body.get("name", "")
                print(f"✓ Posted message to #{room} as HUMAN ({operator}) -> {msg_name}")
                return 0
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            sys.stderr.write(f"Google Chat API error ({exc.code}): {err_body}\n")
            return 1

    # Mode 1: Send as Agent (Default — distinct Agent identity / Zero-Key Pub/Sub Relay)
    normalized_via = (via or "auto").strip().lower()

    # 1a. Explicit or auto Webhook URL
    if normalized_via in ("auto", "direct") and webhook_url and webhook_url.startswith("https://chat.googleapis.com/"):
        target_url = append_thread_query_params(webhook_url, thread_key)
        req = urllib.request.Request(
            target_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=UTF-8"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                msg_name = body.get("name", "")
                print(f"✓ Posted message to #{room} as AGENT via webhook ({msg_name})")
                return 0
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            sys.stderr.write(f"Google Chat webhook error ({exc.code}): {err_body}\n")
            return 1

    # 1b. Dedicated Agent OAuth seat (e.g. [DTTW] Agent OAuth token / gchat_agent_oauth.json)
    if normalized_via in ("auto", "direct") and space_id and agent_bearer_token:
        base_url = f"https://chat.googleapis.com/v1/{space_id}/messages"
        target_url = append_thread_query_params(base_url, thread_key)
        req = urllib.request.Request(
            target_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json; charset=UTF-8",
                "Authorization": f"Bearer {agent_bearer_token}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                msg_name = body.get("name", "")
                print(f"✓ Posted message to #{room} as AGENT via dedicated Agent seat ({msg_name})")
                return 0
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            sys.stderr.write(f"Google Chat Agent seat error ({exc.code}): {err_body}\n")
            return 1

    # 1c. Zero-Key GCP Pub/Sub Agent Relay (`{{PUBSUB_TOPIC_ID}}` -> relayed by dedicated Agent seat)
    if normalized_via in ("auto", "pubsub"):
        pubsub_token, pubsub_src = resolve_pubsub_adc_bearer_token(cfg)
        if pubsub_token:
            ok, info = publish_gchat_relay_via_pubsub(cfg, relay_envelope, pubsub_token)
            if ok:
                print(f"✓ Queued AGENT post to #{room} ({space_id}) via Zero-Key Pub/Sub Relay [{pubsub_src}] -> {info}")
                return 0
            if normalized_via == "pubsub":
                sys.stderr.write(f"Failed to publish AGENT post via Pub/Sub relay: {info}\n")
                return 1
        elif normalized_via == "pubsub":
            sys.stderr.write(
                "No Zero-Key `gcloud` ADC token available for `--via pubsub`. "
                "Run `gcloud auth application-default login` or set `PUBSUB_BEARER_TOKEN`.\n"
            )
            return 1

    # 1d. Fallback to personal OAuth token with explicit `*[Operator's Agent on behalf of Operator]*` banner
    if normalized_via in ("auto", "direct") and space_id and human_bearer_token:
        base_url = f"https://chat.googleapis.com/v1/{space_id}/messages"
        target_url = append_thread_query_params(base_url, thread_key)
        req = urllib.request.Request(
            target_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json; charset=UTF-8",
                "Authorization": f"Bearer {human_bearer_token}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                msg_name = body.get("name", "")
                print(f"✓ Posted message to #{room} as AGENT (prefixed via personal OAuth) -> {msg_name}")
                return 0
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            sys.stderr.write(f"Google Chat API error ({exc.code}): {err_body}\n")
            return 1

    sys.stderr.write(
        f"Room '#{room}' ({space_id}) requires either Zero-Key `gcloud` ADC (`gcloud auth application-default login`) "
        f"for Mode 1 (`--send-as agent`) or Google Chat OAuth (`gchat.py auth-login`) for Mode 2 (`--send-as human`).\n"
    )
    return 1


def cmd_list_messages(
    room: str,
    limit: int = 15,
    cfg_path: Path = CONFIG_PATH,
    as_json: bool = False,
    oauth_path: Path = OAUTH_TOKEN_PATH,
    agent_oauth_path: Path = AGENT_OAUTH_TOKEN_PATH,
) -> int:
    cfg = load_state_config(cfg_path)
    rooms = cfg.get("gchat_rooms") or {}
    r_cfg = rooms.get(room) or {}
    _, space_id, bearer_token = get_room_config(cfg, room, oauth_path=oauth_path)
    if not bearer_token:
        bearer_token, _ = resolve_agent_bearer_token(cfg, r_cfg, agent_oauth_path=agent_oauth_path)
    if not space_id or not bearer_token:
        sys.stderr.write(
            f"Reading history from '#{room}' ({space_id}) requires Google Chat OAuth credentials "
            f"(`gchat.py auth-login` or `GCHAT_BEARER_TOKEN`).\n"
        )
        return 1

    url = f"https://chat.googleapis.com/v1/{space_id}/messages?pageSize={max(1, min(100, limit))}&orderBy=createTime%20desc"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {bearer_token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            messages = body.get("messages") or []
            if as_json:
                print(json.dumps(messages, indent=2))
                return 0
            print(f"=== Recent {len(messages)} Message(s) in #{room} ({space_id}) ===")
            for m in reversed(messages):
                sender = (m.get("sender") or {}).get("displayName") or (m.get("sender") or {}).get("name") or "Unknown"
                ctime = m.get("createTime", "")
                txt = (m.get("text") or "").replace("\n", " ")
                print(f"[{ctime}] {sender}: {txt}")
            return 0
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        sys.stderr.write(f"Google Chat API error ({exc.code}): {err_body}\n")
        return 1


class GChatSelfTests(unittest.TestCase):
    def test_extract_space_id_from_webhook(self) -> None:
        sample = "https://chat.googleapis.com/v1/spaces/AAAA1234xyz/messages?key=AIzaFake&token=FakeTok"
        self.assertEqual(extract_space_id(sample), "spaces/AAAA1234xyz")

    def test_append_thread_query_params(self) -> None:
        sample = "https://chat.googleapis.com/v1/spaces/AAAA1234xyz/messages?key=k1&token=t1"
        threaded = append_thread_query_params(sample, "sync-thread-1")
        self.assertIn("threadKey=sync-thread-1", threaded)
        self.assertIn("messageReplyOption=REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD", threaded)

    def test_build_spaces_setup_payload_omits_external_flag_for_gmail(self) -> None:
        payload = build_spaces_setup_payload(
            display_name="dttw — #humans",
            invite_emails=["peer1@example.com", "peer2@example.com"],
        )
        self.assertEqual(payload["space"]["displayName"], "dttw — #humans")
        self.assertNotIn("externalUserAllowed", payload["space"])
        self.assertEqual(len(payload["memberships"]), 2)
        self.assertEqual(payload["memberships"][0]["member"]["name"], "users/peer1@example.com")

    def test_build_message_payload_with_agent_prefix_and_card(self) -> None:
        payload = build_message_payload(
            text="UniFi playbook verified.",
            operator="andrew",
            as_agent=True,
            card_title="Commons Update",
            card_subtitle="Phase 5",
        )
        self.assertTrue(payload["text"].startswith("*[Andrew's Agent on behalf of Andrew]*"))
        self.assertEqual(payload["cardsV2"][0]["card"]["header"]["title"], "Commons Update")

    def test_build_message_payload_as_human_omits_agent_prefix(self) -> None:
        payload = build_message_payload(
            text="Hey guys, checking in directly as Andrew.",
            operator="andrew",
            as_agent=False,
        )
        self.assertEqual(payload["text"], "Hey guys, checking in directly as Andrew.")
        self.assertNotIn("Agent on behalf of", payload["text"])

    def test_build_pubsub_relay_envelope(self) -> None:
        env = build_pubsub_relay_envelope(
            operator="carl",
            room="backchannel",
            space_id="spaces/{{GCHAT_BACKCHANNEL_SPACE_ID}}",
            text="Heartbeat from Carl's agent",
            thread_key="hb-1",
        )
        self.assertEqual(env["event"], "gchat_relay_post")
        self.assertEqual(env["sender"], "carl")
        self.assertEqual(env["send_as"], "agent")
        self.assertEqual(env["room"], "backchannel")
        self.assertEqual(env["space_id"], "spaces/{{GCHAT_BACKCHANNEL_SPACE_ID}}")
        self.assertEqual(env["thread_key"], "hb-1")

    def test_save_state_config_atomic_0600(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = Path(tmpdir) / "config.json"
            save_state_config({"operator": "jon"}, path=cfg_path)
            self.assertEqual(cfg_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(load_state_config(path=cfg_path)["operator"], "jon")

    def test_extract_code_from_redirect_url(self) -> None:
        url = "http://127.0.0.1:8765/?state=xyz&code=4/0AeanS0SampleCode123&scope=https://www.googleapis.com/auth/chat.messages"
        self.assertEqual(extract_code_from_input(url), "4/0AeanS0SampleCode123")

    def test_resolve_pubsub_target_parameterization(self) -> None:
        self.assertEqual(resolve_pubsub_target({}), ("{{PUBSUB_PROJECT_ID}}", "{{PUBSUB_TOPIC_ID}}"))
        custom = {"pubsub": {"project_id": "custom-dttw-proj", "topic_id": "custom-topic"}}
        self.assertEqual(resolve_pubsub_target(custom), ("custom-dttw-proj", "custom-topic"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Direct Google Chat CLI for Antigravity (/gchat)")
    parser.add_argument("--self-test", action="store_true", help="Run verification unit tests")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("status", help="Show configured Google Chat rooms and Dual-Identity auth status")

    p_auth = sub.add_parser("auth-login", help="Authorize Google Chat OAuth 2.0 (saves auto-refreshing token in ~/.gemini/state/gchat_oauth.json)")
    p_auth.add_argument("--client-secrets", default=None, help="Path to OAuth Desktop client_secret.json")
    p_auth.add_argument("--client-id", default=None, help="OAuth 2.0 Client ID")
    p_auth.add_argument("--client-secret", default=None, help="OAuth 2.0 Client Secret")
    p_auth.add_argument("--port", type=int, default=8765, help="Local loopback port (default: 8765)")
    p_auth.add_argument("--no-browser", action="store_true", help="Print OAuth URL for headless/Cloud VM login")
    p_auth.add_argument("--code", default=None, help="Authorization code or full http://127.0.0.1:8765/?code=... redirect URL")
    p_auth.add_argument(
        "--agent-seat",
        action="store_true",
        help="Save token to ~/.gemini/state/gchat_agent_oauth.json (dedicated Agent seat) instead of personal gchat_oauth.json",
    )

    p_create = sub.add_parser("create-space", help="Programmatically create a Google Chat space and invite members via POST /v1/spaces:setup")
    p_create.add_argument("--room", required=True, help="Logical room name (e.g. humans or backchannel)")
    p_create.add_argument("--display-name", required=True, help="Space display name (e.g. 'dttw — #humans')")
    p_create.add_argument("--invite", nargs="*", default=[], help="Email addresses to invite into the space")
    p_create.add_argument("--dry-run", action="store_true", help="Print JSON payload without sending HTTP request")

    p_set = sub.add_parser("set-webhook", help="Save a Google Chat webhook URL or op:// pointer in ~/.gemini/state/config.json")
    p_set.add_argument("--room", required=True, help="Logical room name (e.g. humans or backchannel)")
    p_set.add_argument("--url", required=True, help="Incoming webhook URL or op:// URI")
    p_set.add_argument("--space-id", default=None, help="Optional explicit spaces/<ID>")

    p_post = sub.add_parser("post", help="Post a message or Card v2 to a Google Chat room (--send-as agent | --send-as human)")
    p_post.add_argument("--room", default="humans", help="Logical room name (default: humans)")
    p_post.add_argument("--text", required=True, help="Message text")
    p_post.add_argument("--thread-key", default=None, help="Optional thread key for threaded replies")
    p_post.add_argument("--card-title", default=None, help="Optional Card v2 header title")
    p_post.add_argument("--card-subtitle", default=None, help="Optional Card v2 header subtitle")
    p_post.add_argument(
        "--send-as",
        choices=["agent", "human"],
        default="agent",
        help="Sender identity: 'agent' (default: distinct Agent identity / Zero-Key Pub/Sub relay) or 'human' (impersonate personal @gmail.com via gchat_oauth.json)",
    )
    p_post.add_argument(
        "--via",
        choices=["auto", "pubsub", "direct"],
        default="auto",
        help="Transport route for --send-as agent: 'auto' (default), 'pubsub' ({{PUBSUB_TOPIC_ID}} relay), or 'direct' (Chat REST API)",
    )
    p_post.add_argument("--no-agent-prefix", action="store_true", help="Alias for `--send-as human` (omit *[Operator's Agent]* prefix)")
    p_post.add_argument("--dry-run", action="store_true", help="Print JSON payload without sending HTTP request")

    p_list = sub.add_parser("list-messages", help="Read recent messages from a space via Google Chat REST API")
    p_list.add_argument("--room", default="humans", help="Logical room name (default: humans)")
    p_list.add_argument("--limit", type=int, default=15, help="Max messages to retrieve")
    p_list.add_argument("--json", action="store_true", help="Output raw JSON message list")

    args = parser.parse_args()
    if args.self_test:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(GChatSelfTests)
        res = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if res.wasSuccessful() else 1

    if args.cmd == "status" or not args.cmd:
        return cmd_status()
    if args.cmd == "auth-login":
        target_oauth_path = AGENT_OAUTH_TOKEN_PATH if args.agent_seat else OAUTH_TOKEN_PATH
        return cmd_auth_login(
            client_secrets_path=args.client_secrets,
            client_id_arg=args.client_id,
            client_secret_arg=args.client_secret,
            port=args.port,
            no_browser=args.no_browser,
            auth_code=args.code,
            oauth_path=target_oauth_path,
        )
    if args.cmd == "create-space":
        return cmd_create_space(args.room, args.display_name, args.invite, args.dry_run)
    if args.cmd == "set-webhook":
        return cmd_set_webhook(args.room, args.url, args.space_id)
    if args.cmd == "post":
        effective_send_as = "human" if args.no_agent_prefix else args.send_as
        return cmd_post(
            room=args.room,
            text=args.text,
            thread_key=args.thread_key,
            card_title=args.card_title,
            card_subtitle=args.card_subtitle,
            send_as=effective_send_as,
            via=args.via,
            dry_run=args.dry_run,
        )
    if args.cmd == "list-messages":
        return cmd_list_messages(args.room, args.limit, as_json=args.json)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

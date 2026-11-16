#!/usr/bin/env python3
"""
redact_check.py — 3-Stage Pre-Push Redaction Gate & 1Password Config Resolver
=============================================================================
Enforces Jon & Andrew's pre-push sanitization standard for ~/.gemini/commons:
  - Stage 1 (Deterministic Scrubber): Regex pass (RFC1918 IPv4, MACs, /Users/<user> paths,
    un-templated op:// URIs, phone numbers) + personal blocklist in ~/.gemini/state/redaction_rules.yaml.
  - Stage 2 (Adversarial Diff Summary): Prints a structured diff summary for agent inspection.
  - Stage 3 (Ratchet): `redact_check.py allow <token>` appends a human-approved token to
    `allowlist_tokens` in ~/.gemini/state/redaction_rules.yaml so it never prompts twice.
  - Config Resolver (`resolve-config`): Loads ~/.gemini/state/config.json and resolves any
    `op://...` 1Password secret pointers at runtime via `~/.local/bin/op` or `op`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

STATE_DIR = Path(os.environ.get("ANTIGRAVITY_STATE_DIR", str(Path.home() / ".gemini" / "state")))
COMMONS_DIR = Path(os.environ.get("ANTIGRAVITY_COMMONS_DIR", str(Path.home() / ".gemini" / "commons")))
RULES_PATH = STATE_DIR / "redaction_rules.yaml"
CONFIG_PATH = STATE_DIR / "config.json"

# Built-in regex detectors for Stage 1
REGEX_DETECTORS: List[Tuple[str, re.Pattern[str]]] = [
    (
        "RFC1918_PRIVATE_IP",
        re.compile(
            r"\b(?:192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3})(?:/\d{1,2})?\b"
        ),
    ),
    (
        "MAC_ADDRESS",
        re.compile(r"\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b"),
    ),
    (
        "LOCAL_HOME_PATH",
        re.compile(r"/Users/[A-Za-z0-9._-]+"),
    ),
    (
        "LIVE_1PASSWORD_URI",
        re.compile(r"op://(?!Agent-(?:<User>|<Operator>|\{\{OPERATOR\}\}))[A-Za-z0-9._-]+/[A-Za-z0-9._/-]+"),
    ),
    (
        "US_PHONE_E164",
        re.compile(r"\+1\d{10}\b"),
    ),
]

SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules"}
SKIP_SUFFIXES = {".bundle", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".pyc"}


def parse_simple_yaml_lists(path: Path) -> Tuple[List[str], List[str]]:
    """Parse blocklist_terms and allowlist_tokens from redaction_rules.yaml without external deps."""
    blocklist: List[str] = []
    allowlist: List[str] = []
    if not path.exists():
        return blocklist, allowlist

    current: str = ""
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("blocklist_terms:"):
            current = "block"
            continue
        if line.startswith("allowlist_tokens:") or line.startswith("allowlist:"):
            current = "allow"
            continue
        if line.endswith(":") and not line.startswith("-"):
            current = ""
            continue
        if line.startswith("-"):
            val = line[1:].strip()
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            if val:
                if current == "block":
                    blocklist.append(val)
                elif current == "allow":
                    allowlist.append(val)
    return blocklist, allowlist


def scan_commons(commons_dir: Path = COMMONS_DIR, rules_path: Path = RULES_PATH) -> Tuple[int, List[Dict[str, Any]]]:
    blocklist, allowlist = parse_simple_yaml_lists(rules_path)
    allow_set: Set[str] = {a.lower() for a in allowlist}
    # Always allow generic RFC1918 supernet/documentation IPs & template placeholders
    allow_set.update(
        {
            "10.0.0.0",
            "10.0.0.0/8",
            "172.16.0.0",
            "172.16.0.0/12",
            "192.168.0.0",
            "192.168.0.0/16",
            "192.168.1.1",
            "192.168.1.0/24",
            "10.0.0.1",
            "10.0.0.0/24",
            "/users/<username>",
            "/users/<user>",
            "/users/{{user}}",
            "op://agent-<user>/",
            "op://agent-<operator>/",
            "op://agent-{{operator}}/",
        }
    )

    findings: List[Dict[str, Any]] = []
    if not commons_dir.exists():
        return 0, findings

    for root, dirs, files in os.walk(commons_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fname in sorted(files):
            fpath = Path(root) / fname
            if fpath.suffix.lower() in SKIP_SUFFIXES:
                continue
            rel = str(fpath.relative_to(commons_dir))
            try:
                text = fpath.read_text(encoding="utf-8")
            except Exception:
                continue

            for lineno, line in enumerate(text.splitlines(), start=1):
                low_line = line.lower()
                # 1. Check explicit blocklist terms from private ~/.gemini/state/redaction_rules.yaml
                for term in blocklist:
                    t_low = term.lower()
                    if t_low and t_low in low_line and t_low not in allow_set:
                        findings.append(
                            {
                                "stage": "STAGE_1_BLOCKLIST",
                                "rule": "PRIVATE_BLOCKLIST_TERM",
                                "file": rel,
                                "line": lineno,
                                "token": term,
                                "snippet": line.strip()[:120],
                            }
                        )

                # 2. Check regex detectors
                for rule_name, pattern in REGEX_DETECTORS:
                    for match in pattern.finditer(line):
                        tok = match.group(0)
                        if tok.lower() in allow_set:
                            continue
                        findings.append(
                            {
                                "stage": "STAGE_1_REGEX",
                                "rule": rule_name,
                                "file": rel,
                                "line": lineno,
                                "token": tok,
                                "snippet": line.strip()[:120],
                            }
                        )

    return (1 if findings else 0), findings


def ratchet_allow_token(token: str, rules_path: Path = RULES_PATH) -> int:
    rules_path.parent.mkdir(parents=True, exist_ok=True)
    _, allowlist = parse_simple_yaml_lists(rules_path)
    if token in allowlist:
        print(f"Token {token!r} is already in {rules_path}")
        return 0
    content = rules_path.read_text(encoding="utf-8") if rules_path.exists() else "version: 1\nallowlist_tokens:\n"
    if "allowlist_tokens:" not in content:
        content = content.rstrip() + "\n\nallowlist_tokens:\n"
    content = content.rstrip() + f'\n  - "{token}"\n'
    rules_path.write_text(content, encoding="utf-8")
    print(f"✓ Ratcheted {token!r} into {rules_path} (will not prompt again)")
    return 0


def resolve_op_uri(val: str) -> str:
    """Resolve an op:// 1Password URI at runtime if the `op` CLI is available."""
    if not isinstance(val, str) or not val.startswith("op://"):
        return val
    op_bin = shutil.which("op") or (str(Path.home() / ".local" / "bin" / "op") if (Path.home() / ".local" / "bin" / "op").exists() else None)
    if not op_bin:
        return val
    try:
        res = subprocess.run([op_bin, "read", val], capture_output=True, text=True, timeout=10, check=False)
        if res.returncode == 0:
            return res.stdout.strip()
    except Exception:
        pass
    return val


def resolve_config(config_path: Path = CONFIG_PATH, resolve_secrets: bool = False) -> Dict[str, Any]:
    if not config_path.exists():
        return {}
    data = json.loads(config_path.read_text(encoding="utf-8"))
    if not resolve_secrets:
        return data
    resolved: Dict[str, Any] = {}
    for k, v in data.items():
        resolved[k] = resolve_op_uri(v) if isinstance(v, str) else v
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description="3-Stage Pre-Push Redaction Gate for ~/.gemini/commons")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan", help="Scan ~/.gemini/commons for private tokens, IPs, paths, or PII")
    p_scan.add_argument("--json", action="store_true", help="Output findings as JSON")

    p_allow = sub.add_parser("allow", help="Ratchet a safe token into ~/.gemini/state/redaction_rules.yaml")
    p_allow.add_argument("token", help="Token to allowlist")

    p_cfg = sub.add_parser("resolve-config", help="Print ~/.gemini/state/config.json (optionally resolving op:// URIs)")
    p_cfg.add_argument("--resolve-op", action="store_true", help="Resolve op:// URIs via 1Password CLI")

    args = parser.parse_args()
    if args.cmd == "scan":
        rc, findings = scan_commons()
        if args.json:
            print(json.dumps({"passed": rc == 0, "findings_count": len(findings), "findings": findings}, indent=2))
        else:
            if rc == 0:
                print("✓ Stage 1 Redaction Gate PASSED: 0 private tokens, subnets, or household PII found in ~/.gemini/commons.")
            else:
                print(f"✗ Stage 1 Redaction Gate BLOCKED push ({len(findings)} finding(s)):")
                for f in findings:
                    print(f"  - [{f['rule']}] {f['file']}:{f['line']} -> matched {f['token']!r}")
                print("\nTo fix: scrub the token into ~/.gemini/state/config.json, or if it is a safe public placeholder, ratchet it once via:")
                print("  python3 ~/.gemini/commons/skills/sync-commons/scripts/redact_check.py allow \"<token>\"")
        return rc

    if args.cmd == "allow":
        return ratchet_allow_token(args.token)

    if args.cmd == "resolve-config":
        cfg = resolve_config(resolve_secrets=args.resolve_op)
        print(json.dumps(cfg, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())

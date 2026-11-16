#!/usr/bin/env python3
"""Three-Stage Outbound Redaction Gate (`redact-gate`) for ~/.gemini/commons.

- Stage 1: Deterministic regex + `~/.gemini/state/redaction_rules.yaml` (and optional `op://`) dictionary replacement.
- Stage 2: Heuristic ambiguity scanner for unredacted SSIDs, VLAN numbers, emails, or potential PII.
- Stage 3: Self-learning ratchet (`--ratchet TOKEN=PLACEHOLDER`) that persists new rules to `~/.gemini/state/redaction_rules.yaml`.

Zero external dependencies (Python 3 standard library only).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

DEFAULT_RULES_PATH = Path.home() / ".gemini" / "state" / "redaction_rules.yaml"
DEFAULT_MESH_PATH = Path.home() / ".gemini" / "mesh" / "mesh.json"


def _load_mesh_safe_doc_ids(mesh_path: Path = DEFAULT_MESH_PATH) -> str:
    """Load allowlisted peer mesh Google Doc/Drive IDs from Ring 2 (~/.gemini/mesh/mesh.json) if present."""
    ids: List[str] = ["EXAMPLE_SAFE_DOC_ID_0000000000"]
    if mesh_path.is_file():
        try:
            data = json.loads(mesh_path.read_text(encoding="utf-8"))
            for item in data.get("safe_commons_doc_ids") or []:
                s = str(item).strip()
                if s and not s.startswith("{{"):
                    ids.append(re.escape(s))
        except Exception:
            pass
    return "|".join(ids)


SAFE_COMMONS_DOC_IDS = _load_mesh_safe_doc_ids()

BUILTIN_REGEX_RULES: List[Tuple[str, str, str]] = [
    (
        "rfc1918_cidr",
        r"\b(?!(?:10\.0\.0\.0/8|172\.16\.0\.0/12|192\.168\.0\.0/16|192\.168\.1\.0/24|10\.0\.0\.0/24)\b)(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3})/\d{1,2}\b",
        "{{RFC1918_CIDR}}",
    ),
    (
        "rfc1918_ip",
        r"\b(?!(?:10\.0\.0\.0|172\.16\.0\.0|192\.168\.0\.0|192\.168\.1\.0|192\.168\.1\.1|10\.0\.0\.1)\b)(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3})\b",
        "{{RFC1918_IP}}",
    ),
    (
        "mac_address",
        r"\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b",
        "{{MAC_ADDRESS}}",
    ),
    (
        "local_mdns_hostname",
        r"(?<![._])\b(?![a-zA-Z0-9_-]*\{\{)(?!_[a-zA-Z0-9_-]+\._(?:tcp|udp)\.)[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*\.(?:local|lan|internal|home\.arpa)\b",
        "{{INTERNAL_HOSTNAME}}",
    ),
    (
        "macos_user_path",
        r"/Users/(?!\{\{USER\}\}|<)[a-zA-Z0-9._-]+",
        "/Users/{{USER}}",
    ),
    (
        "google_doc_or_drive_url_id",
        rf"(https://(?:docs|drive)\.google\.com/(?:document|spreadsheets|presentation|file)/d/)(?!\{{{{|{SAFE_COMMONS_DOC_IDS})[a-zA-Z0-9_-]{{25,50}}",
        r"\1{{GOOGLE_DOC_ID}}",
    ),
    (
        "google_drive_folder_url_id",
        rf"(https://drive\.google\.com/drive/(?:u/\d+/)?folders/)(?!\{{{{|{SAFE_COMMONS_DOC_IDS})[a-zA-Z0-9_-]{{25,50}}",
        r"\1{{GOOGLE_DRIVE_FOLDER_ID}}",
    ),
]

AMBIGUITY_PATTERNS: List[Tuple[str, str]] = [
    ("raw_email_address", r"\b[a-zA-Z0-9._%+-]+@(?!example\.(?:com|org|net)\b|invalid\b|test\b)[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b"),
    ("hardcoded_ssid_assignment", r"(?i)\bssid\s*[:=]\s*['\"]?(?!\{\{)[A-Za-z0-9_-]{3,}['\"]?"),
    ("unparameterized_op_vault", r"op://Agent-(?!\{\{|<)[A-Za-z0-9_-]+/"),
]


def _parse_simple_yaml_dict(path: Path) -> Tuple[Dict[str, str], List[str], List[str]]:
    """Minimal zero-dependency parser for dictionary_replacements, ratcheted_replacements,
    blocklist_terms, and allowlist_tokens in redaction_rules.yaml."""
    if not path.is_file():
        return {}, [], []
    replacements: Dict[str, str] = {}
    blocklist: List[str] = []
    allowlist: List[str] = []
    current_section: str = ""
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not raw_line.startswith(" ") and stripped.endswith(":"):
            current_section = stripped[:-1]
            continue
        if current_section in ("dictionary_replacements", "ratcheted_replacements") and ":" in stripped:
            if stripped.endswith("{}"):
                continue
            k, v = stripped.split(":", 1)
            k = k.strip().strip("'\"")
            v = v.strip().strip("'\"")
            if k and v:
                replacements[k] = v
        elif current_section in ("blocklist_terms", "allowlist_tokens", "allowlist") and stripped.startswith("-"):
            val = stripped[1:].strip().strip("'\"")
            if val and not val.startswith("<"):
                if current_section == "blocklist_terms":
                    blocklist.append(val)
                else:
                    allowlist.append(val)
    return replacements, blocklist, allowlist


def append_ratchet_rule(path: Path, token: str, placeholder: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        path.write_text(
            "version: 1\ndictionary_replacements:\nratcheted_replacements:\n",
            encoding="utf-8",
        )
    text = path.read_text(encoding="utf-8")
    entry = f'  "{token}": "{placeholder}"\n'
    if "ratcheted_replacements: {}" in text:
        text = text.replace("ratcheted_replacements: {}", f"ratcheted_replacements:\n{entry.rstrip()}")
    elif "ratcheted_replacements:" in text:
        text = text.replace("ratcheted_replacements:\n", f"ratcheted_replacements:\n{entry}")
    else:
        text = text.rstrip() + f"\n\nratcheted_replacements:\n{entry}"
    path.write_text(text, encoding="utf-8")


def scrub_content(
    content: str,
    dict_rules: Dict[str, str],
    blocklist_terms: List[str] | None = None,
    allowlist_tokens: List[str] | None = None,
) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]]]:
    scrubbed = content
    stage1_hits: List[Dict[str, Any]] = []
    allow_lower = {t.lower() for t in (allowlist_tokens or [])}

    # 1. Apply dictionary & ratcheted token replacements (longest tokens first)
    for token in sorted(dict_rules.keys(), key=len, reverse=True):
        placeholder = dict_rules[token]
        pattern = re.compile(re.escape(token), re.IGNORECASE)
        matches = list(pattern.findall(scrubbed))
        if matches:
            scrubbed = pattern.sub(placeholder, scrubbed)
            stage1_hits.append(
                {
                    "type": "dictionary",
                    "rule": token,
                    "replacement": placeholder,
                    "count": len(matches),
                }
            )

    # 2. Apply built-in regex rules
    for name, regex_str, replacement in BUILTIN_REGEX_RULES:
        pattern = re.compile(regex_str)
        matches = list(pattern.findall(scrubbed))
        if matches:
            scrubbed = pattern.sub(replacement, scrubbed)
            stage1_hits.append(
                {
                    "type": "regex",
                    "rule": name,
                    "replacement": replacement,
                    "count": len(matches),
                }
            )

    # 3. Stage 2: Scan scrubbed output for remaining ambiguities + personal blocklist_terms from Ring 1
    stage2_ambiguities: List[Dict[str, Any]] = []
    dynamic_patterns: List[Tuple[str, str]] = list(AMBIGUITY_PATTERNS)
    for bterm in (blocklist_terms or []):
        dynamic_patterns.append(("ring1_blocklist_term", rf"(?i)\b{re.escape(bterm)}\b"))

    for lineno, line in enumerate(scrubbed.splitlines(), start=1):
        for name, pat_str in dynamic_patterns:
            for m in re.finditer(pat_str, line):
                val = m.group(0)
                if "{{" in val or "<" in val or val.lower() in allow_lower:
                    continue
                stage2_ambiguities.append(
                    {
                        "rule": name,
                        "line": lineno,
                        "match": val,
                        "context": line.strip()[:120],
                    }
                )

    return scrubbed, stage1_hits, stage2_ambiguities


def iter_target_files(target: Path) -> List[Path]:
    if target.is_file():
        return [target]
    files: List[Path] = []
    for root, dirs, filenames in os.walk(target):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", ".venv", "node_modules")]
        for fn in sorted(filenames):
            p = Path(root) / fn
            if p.suffix.lower() in (".md", ".py", ".sh", ".json", ".yaml", ".yml", ".txt", ".toml"):
                files.append(p)
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description="3-Stage Outbound Redaction Gate for ~/.gemini/commons")
    parser.add_argument("paths", nargs="*", help="Files or directories to check or scrub")
    parser.add_argument("--rules", default=str(DEFAULT_RULES_PATH), help="Path to redaction_rules.yaml")
    parser.add_argument("--check", action="store_true", help="Dry-run audit and print JSON report")
    parser.add_argument("--in-place", action="store_true", help="Scrub files in-place")
    parser.add_argument(
        "--ratchet",
        metavar="TOKEN=PLACEHOLDER",
        help="Stage 3: Append a new token=placeholder rule to ~/.gemini/state/redaction_rules.yaml",
    )
    args = parser.parse_args()

    rules_path = Path(args.rules).expanduser()

    if args.ratchet:
        if "=" not in args.ratchet:
            print("Error: --ratchet requires TOKEN=PLACEHOLDER format", file=sys.stderr)
            return 1
        tok, repl = args.ratchet.split("=", 1)
        append_ratchet_rule(rules_path, tok.strip(), repl.strip())
        print(json.dumps({"status": "ratcheted", "token": tok.strip(), "replacement": repl.strip(), "rules_file": str(rules_path)}, indent=2))
        return 0

    if not args.paths:
        parser.print_help()
        return 1

    dict_rules, blocklist_terms, allowlist_tokens = _parse_simple_yaml_dict(rules_path)
    report_files: List[Dict[str, Any]] = []
    total_ambiguities = 0

    for raw_p in args.paths:
        for file_path in iter_target_files(Path(raw_p).expanduser()):
            original = file_path.read_text(encoding="utf-8", errors="replace")
            scrubbed, s1_hits, s2_flags = scrub_content(
                original, dict_rules, blocklist_terms, allowlist_tokens
            )
            modified = scrubbed != original
            if args.in_place and modified:
                file_path.write_text(scrubbed, encoding="utf-8")
            total_ambiguities += len(s2_flags)
            report_files.append(
                {
                    "file": str(file_path),
                    "modified": modified,
                    "stage1_replacements": s1_hits,
                    "stage2_ambiguities": s2_flags,
                }
            )

    summary = {
        "status": "CLEAN_AUTO_PUBLISH_READY" if total_ambiguities == 0 else "NEEDS_ADVERSARIAL_OR_HUMAN_REVIEW",
        "rules_loaded": len(dict_rules),
        "total_files_scanned": len(report_files),
        "total_stage2_ambiguities": total_ambiguities,
        "files": report_files,
    }
    print(json.dumps(summary, indent=2))
    return 0 if total_ambiguities == 0 else 2


if __name__ == "__main__":
    sys.exit(main())

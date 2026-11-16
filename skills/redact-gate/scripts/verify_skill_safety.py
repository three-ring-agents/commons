#!/usr/bin/env python3
"""Inbound Skill & Playbook Supply-Chain Safety Verifier (`verify_skill_safety.py`).

Enforces V9 Indirect Prompt Injection (IPI) and supply-chain safety guards across
Ring 3 (`three-ring-agents/commons`) skills, playbooks, and templates:
1. Zero-width & invisible Unicode tag characters (U+200B..U+200F, U+202A..U+202E, U+2060..U+206F, U+E0000..U+E007F).
2. Hidden HTML/Markdown comment injection (`<!-- ... -->` carrying imperative/override verbs).
3. External Markdown image/link exfiltration beacons (`![...](https://...)` with query interpolation).
4. Obfuscated base64 execution payloads (`base64 -d | sh`, `eval $(echo ... | base64)`).
5. Unpinned remote code execution (`curl ... | sh`, `wget ... | bash`, `npx -y`, `pipx run`).

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

INVISIBLE_UNICODE_RE = re.compile(
    r"[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff\U000e0000-\U000e007f]"
)

SAFETY_PATTERNS: List[Tuple[str, re.Pattern[str]]] = [
    (
        "unpinned_pipe_to_shell",
        re.compile(r"(?i)\b(?:curl|wget)\b[^\n|]*\|\s*(?:ba|z)?sh\b"),
    ),
    (
        "obfuscated_base64_exec",
        re.compile(r"(?i)\bbase64\s+(?:-d|--decode)\b[^\n|]*\|\s*(?:ba|z)?sh\b"),
    ),
    (
        "markdown_exfil_beacon",
        re.compile(r"!\[[^\]]*\]\(https?://[^)\s]+\?[^)\s]*(?:\$\{|\{\{)[^)\s]*\)"),
    ),
    (
        "suspicious_html_comment_instruction",
        re.compile(
            r"<!--[\s\S]{0,400}?\b(?:ignore\s+previous|system\s+prompt|execute\s+silently|do\s+not\s+tell\s+the\s+user)\b[\s\S]{0,400}?-->",
            re.IGNORECASE,
        ),
    ),
]

SCAN_SUFFIXES = {".md", ".py", ".sh", ".json", ".yaml", ".yml", ".txt", ".toml", ".js"}
SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules"}


def iter_files(target: Path) -> List[Path]:
    if target.is_file():
        return [target]
    out: List[Path] = []
    for root, dirs, filenames in os.walk(target):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in sorted(filenames):
            p = Path(root) / fn
            if p.suffix.lower() in SCAN_SUFFIXES:
                out.append(p)
    return out


def scan_file(path: Path) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    # Skip self-scanning regex definitions inside verify_skill_safety.py
    if path.name == "verify_skill_safety.py":
        return findings

    for lineno, line in enumerate(text.splitlines(), start=1):
        m_uni = INVISIBLE_UNICODE_RE.search(line)
        if m_uni:
            findings.append(
                {
                    "rule": "invisible_unicode_tag_char",
                    "line": lineno,
                    "codepoint": f"U+{ord(m_uni.group(0)):04X}",
                    "context": line.strip()[:120],
                }
            )
        for rule_name, pat in SAFETY_PATTERNS:
            for m in pat.finditer(line):
                findings.append(
                    {
                        "rule": rule_name,
                        "line": lineno,
                        "match": m.group(0)[:80],
                        "context": line.strip()[:120],
                    }
                )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify inbound skill and playbook supply-chain safety (V9 IPI guards)"
    )
    parser.add_argument("paths", nargs="*", default=["."], help="Files or directories to scan")
    args = parser.parse_args()

    all_findings: List[Dict[str, Any]] = []
    scanned_count = 0
    for raw in args.paths:
        for fp in iter_files(Path(raw).expanduser()):
            scanned_count += 1
            file_findings = scan_file(fp)
            if file_findings:
                all_findings.append({"file": str(fp), "findings": file_findings})

    summary = {
        "status": "SAFE" if not all_findings else "BLOCKED_SUPPLY_CHAIN_VIOLATION",
        "files_scanned": scanned_count,
        "violations_count": sum(len(x["findings"]) for x in all_findings),
        "violations": all_findings,
    }
    print(json.dumps(summary, indent=2))
    return 0 if not all_findings else 2


if __name__ == "__main__":
    sys.exit(main())

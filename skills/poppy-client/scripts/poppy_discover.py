#!/usr/bin/env python3
"""
Poppy v1.0 Discovery, Scope-Hint Tiering & Terms Revision-Hash Helper (stdlib-only).

Maps /.well-known/poppy.json `scope_hints` onto Tier 1-3 MPA policies:
  - changes == "none"         -> TIER_1_READ
  - changes == "reversible"   -> TIER_2_STAGE
  - changes == "irreversible" -> TIER_3_MPA_APPROVAL (fail-closed)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict

CHANGE_TIER_MAP = {
    "none": "TIER_1_READ",
    "reversible": "TIER_2_STAGE",
    "irreversible": "TIER_3_MPA_APPROVAL",
}


def map_scope_hint(hint: Dict[str, Any]) -> str:
    """Fail-closed mapping from Poppy scope_hints to Tier 1-3."""
    changes = str(hint.get("changes", "irreversible")).strip().lower()
    return CHANGE_TIER_MAP.get(changes, "TIER_3_MPA_APPROVAL")


def compute_terms_revision_hash(terms_payload: Dict[str, Any]) -> str:
    """Canonical SHA-256 hash for binding Tier 3 MPA/FaceID approvals to exact terms."""
    canonical = json.dumps(terms_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def analyze_manifest(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Summarize channels, OAuth resource metadata, and tiered scopes."""
    scope_hints = manifest.get("scope_hints", {})
    tiered_scopes = {}
    for scope, hint in scope_hints.items():
        if isinstance(hint, dict):
            tiered_scopes[scope] = {
                "tier": map_scope_hint(hint),
                "changes": hint.get("changes", "irreversible"),
                "personal_data": bool(hint.get("personal_data", True)),
            }
    return {
        "poppy_version": manifest.get("poppy_version", "unknown"),
        "channels": list(manifest.get("channels", {}).keys()) if isinstance(manifest.get("channels"), dict) else [],
        "authorization_servers": manifest.get("authorization_servers", []),
        "tiered_scopes": tiered_scopes,
    }


def fetch_poppy_manifest(origin: str, timeout: float = 10.0) -> Dict[str, Any]:
    """Fetch /.well-known/poppy.json from an HTTPS origin."""
    parsed = urllib.parse.urlparse(origin)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"Origin must be a valid https:// URL, got: {origin}")
    url = f"https://{parsed.netloc}/.well-known/poppy.json"
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "three-ring-poppy-client/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run_self_test() -> int:
    sample_manifest = {
        "poppy_version": "1.0",
        "authorization_servers": ["https://auth.example.com"],
        "channels": {"mcp": {"url": "https://api.example.com/mcp"}, "openapi": {"url": "https://api.example.com/openapi.json"}},
        "scope_hints": {
            "orders:read": {"changes": "none", "personal_data": True},
            "cart:stage": {"changes": "reversible", "personal_data": False},
            "orders:purchase": {"changes": "irreversible", "personal_data": True},
            "unknown:action": {"changes": "custom_unknown"},
        },
    }
    summary = analyze_manifest(sample_manifest)
    assert summary["tiered_scopes"]["orders:read"]["tier"] == "TIER_1_READ"
    assert summary["tiered_scopes"]["cart:stage"]["tier"] == "TIER_2_STAGE"
    assert summary["tiered_scopes"]["orders:purchase"]["tier"] == "TIER_3_MPA_APPROVAL"
    assert summary["tiered_scopes"]["unknown:action"]["tier"] == "TIER_3_MPA_APPROVAL"

    terms_a = {"operation_id": "op_123", "amount_usd": "42.00", "currency": "USD"}
    terms_b = {"currency": "USD", "amount_usd": "42.00", "operation_id": "op_123"}
    terms_c = {"operation_id": "op_123", "amount_usd": "420.00", "currency": "USD"}
    assert compute_terms_revision_hash(terms_a) == compute_terms_revision_hash(terms_b)
    assert compute_terms_revision_hash(terms_a) != compute_terms_revision_hash(terms_c)
    print(json.dumps({"status": "ok", "tests_passed": 2, "sample_summary": summary}, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Poppy v1.0 discovery and MPA tiering helper")
    parser.add_argument("--origin", help="Merchant HTTPS origin (e.g. https://shop.example.com)")
    parser.add_argument("--hash-terms", help="Path to operations v3 exact-terms JSON file")
    parser.add_argument("--self-test", action="store_true", help="Run built-in unit tests")
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()
    if args.hash_terms:
        payload = json.loads(Path(args.hash_terms).read_text(encoding="utf-8"))
        print(json.dumps({"terms_revision_hash": compute_terms_revision_hash(payload)}, indent=2))
        return 0
    if args.origin:
        manifest = fetch_poppy_manifest(args.origin)
        print(json.dumps(analyze_manifest(manifest), indent=2))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())

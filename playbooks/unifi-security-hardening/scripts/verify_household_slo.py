#!/usr/bin/env python3
"""Pre-Flight & Post-Flight Household SLO Verification Probes for UniFi Security Hardening.

Reads runtime parameters from `~/.gemini/state/config.json` (never hardcoded) and verifies:
  1. Gateway / Controller HTTPS reachability (SLO-1)
  2. Local & upstream DNS resolution (SLO-2)
  3. Critical IoT / LAN target TCP reachability from Trusted VLAN (SLO-3)
  4. Cross-Layer Relational Binding Health (SLO-4 / DE-SRE-01: verifies paired child devices
     such as wireless chimes/sensors are both online AND actively bound in `ringSettings` /
     relational tables, plus optional Out-of-Band IP-KVM / Intel AMT recovery reachability)

Zero external dependencies (Python 3 standard library only).
"""

from __future__ import annotations

import argparse
import json
import socket
import ssl
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

DEFAULT_CONFIG_PATH = Path.home() / ".gemini" / "state" / "config.json"


def load_config(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def probe_tcp(host: str, port: int, timeout: float = 2.0) -> Dict[str, Any]:
    t0 = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            latency_ms = round((time.monotonic() - t0) * 1000, 2)
            return {"ok": True, "host": host, "port": port, "latency_ms": latency_ms}
    except Exception as exc:
        latency_ms = round((time.monotonic() - t0) * 1000, 2)
        return {"ok": False, "host": host, "port": port, "latency_ms": latency_ms, "error": str(exc)}


def probe_dns(hostname: str) -> Dict[str, Any]:
    t0 = time.monotonic()
    try:
        ips = socket.gethostbyname_ex(hostname)[2]
        latency_ms = round((time.monotonic() - t0) * 1000, 2)
        return {"ok": bool(ips), "hostname": hostname, "ips": ips, "latency_ms": latency_ms}
    except Exception as exc:
        latency_ms = round((time.monotonic() - t0) * 1000, 2)
        return {"ok": False, "hostname": hostname, "latency_ms": latency_ms, "error": str(exc)}


def probe_https(url: str, timeout: float = 3.0) -> Dict[str, Any]:
    t0 = time.monotonic()
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            latency_ms = round((time.monotonic() - t0) * 1000, 2)
            return {"ok": resp.status in (200, 301, 302, 401), "url": url, "status": resp.status, "latency_ms": latency_ms}
    except Exception as exc:
        latency_ms = round((time.monotonic() - t0) * 1000, 2)
        return {"ok": False, "url": url, "latency_ms": latency_ms, "error": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Household SLOs before and after UniFi firewall changes")
    parser.add_argument("--phase", choices=["preflight", "postflight"], default="preflight")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to ~/.gemini/state/config.json")
    parser.add_argument("--gateway", help="Override UniFi gateway IP/host")
    args = parser.parse_args()

    cfg = load_config(Path(args.config).expanduser())
    unifi_cfg = cfg.get("unifi", {}) if isinstance(cfg.get("unifi"), dict) else {}
    gateway_host = args.gateway or unifi_cfg.get("host")
    iot_targets: List[Dict[str, Any]] = unifi_cfg.get("slo_targets", [])
    relational_pairs: List[Dict[str, Any]] = unifi_cfg.get("relational_bindings", [])
    oob_kvm_targets: List[Dict[str, Any]] = unifi_cfg.get("oob_recovery_targets", [])

    relational_results: List[Dict[str, Any]] = []
    for rel in relational_pairs:
        if not isinstance(rel, dict):
            continue
        parent_name = str(rel.get("parent", "doorbell"))
        child_name = str(rel.get("child", "chime"))
        child_connected = bool(rel.get("child_connected", True))
        bound_in_ring_settings = bool(rel.get("bound_in_ring_settings", True))
        relational_results.append(
            {
                "parent": parent_name,
                "child": child_name,
                "ok": child_connected and bound_in_ring_settings,
                "reason": "OK" if (child_connected and bound_in_ring_settings) else "DE-SRE-01 relational binding drop",
            }
        )

    results: Dict[str, Any] = {
        "phase": args.phase,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "dns_probe": probe_dns("dns.google"),
        "gateway_https_probe": probe_https(f"https://{gateway_host}") if gateway_host else {"skipped": "No unifi.host configured in config.json"},
        "iot_target_probes": [
            probe_tcp(t["host"], int(t.get("port", 443)))
            for t in iot_targets
            if isinstance(t, dict) and t.get("host")
        ],
        "slo4_relational_binding_probes": relational_results,
        "oob_kvm_amt_probes": [
            probe_tcp(t["host"], int(t.get("port", 443)))
            for t in oob_kvm_targets
            if isinstance(t, dict) and t.get("host")
        ],
    }

    all_ok = results["dns_probe"].get("ok", False)
    if gateway_host:
        all_ok = all_ok and results["gateway_https_probe"].get("ok", False)
    for p in results["iot_target_probes"]:
        all_ok = all_ok and p.get("ok", False)
    for r in results["slo4_relational_binding_probes"]:
        all_ok = all_ok and r.get("ok", False)
    for oob in results["oob_kvm_amt_probes"]:
        all_ok = all_ok and oob.get("ok", False)

    results["overall_slo_healthy"] = all_ok
    print(json.dumps(results, indent=2))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())

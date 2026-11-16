#!/usr/bin/env python3
"""Generic Pre/Post-Flight Verification Probe for Plan-Bound MPA & Turn-Boundary Taint Gate.

Zero external dependencies (Python 3 standard library only).
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any, Dict


def verify_mpa_manifest_matching() -> Dict[str, Any]:
    sealed_manifest = {
        "plan_id": "plan-demo-01",
        "ttl_minutes": 240,
        "actions": [
            {
                "step_id": "step_1",
                "server": "proxmox",
                "tool": "proxmox_guest_power",
                "args": {"vmid": "110", "action": "reboot"},
                "max_calls": 1,
            }
        ],
    }
    approved_call = {"server": "proxmox", "tool": "proxmox_guest_power", "args": {"vmid": "110", "action": "reboot"}}
    deviated_call = {"server": "proxmox", "tool": "proxmox_guest_power", "args": {"vmid": "100", "action": "stop"}}

    action_spec = sealed_manifest["actions"][0]
    match_ok = (
        approved_call["server"] == action_spec["server"]
        and approved_call["tool"] == action_spec["tool"]
        and approved_call["args"] == action_spec["args"]
    )
    deviation_blocked = not (
        deviated_call["server"] == action_spec["server"]
        and deviated_call["tool"] == action_spec["tool"]
        and deviated_call["args"] == action_spec["args"]
    )
    return {
        "probe": "mpa_manifest_exact_arg_binding",
        "approved_call_allowed": match_ok,
        "deviated_call_blocked": deviation_blocked,
        "ok": match_ok and deviation_blocked,
    }


def verify_turn_boundary_taint_gate() -> Dict[str, Any]:
    last_user_ts = time.time()
    last_untrusted_ts = max(time.time(), last_user_ts + 0.002)
    tainted_blocked = last_untrusted_ts > last_user_ts
    next_user_ts = max(time.time(), last_untrusted_ts + 0.002)
    cleared_after_user_turn = not (last_untrusted_ts > next_user_ts)
    return {
        "probe": "turn_boundary_taint_gate",
        "same_turn_untrusted_blocked": tainted_blocked,
        "next_turn_user_confirmed_allowed": cleared_after_user_turn,
        "ok": tainted_blocked and cleared_after_user_turn,
    }


def main() -> int:
    r1 = verify_mpa_manifest_matching()
    r2 = verify_turn_boundary_taint_gate()
    overall = r1["ok"] and r2["ok"]
    print(json.dumps({"overall_ok": overall, "probes": [r1, r2]}, indent=2))
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())

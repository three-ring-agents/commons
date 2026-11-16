#!/usr/bin/env python3
"""Generic Declarative Daemon Manifest -> macOS launchd (.plist) & Linux systemd (.service/.timer) Compiler.

Zero external dependencies (Python 3 standard library only).
"""

from __future__ import annotations

import argparse
import json
import plistlib
import sys
from typing import Any, Dict


def compile_launchd_plist(manifest: Dict[str, Any]) -> str:
    sched = manifest["schedule"]
    ep = manifest["entrypoint"]
    payload: Dict[str, Any] = {
        "Label": sched["launchd_label"],
        "ProgramArguments": ep["command"],
        "WorkingDirectory": ep["working_dir"],
        "RunAtLoad": False,
        "ProcessType": "Background",
        "Nice": 10,
        "StartInterval": int(sched.get("interval_seconds", 60)),
    }
    return plistlib.dumps(payload).decode("utf-8")


def compile_systemd_timer(manifest: Dict[str, Any]) -> str:
    sched = manifest["schedule"]
    sec = int(sched.get("interval_seconds", 60))
    return (
        f"[Unit]\nDescription=Timer for {manifest['name']}\n\n"
        f"[Timer]\nOnBootSec=30s\nOnUnitActiveSec={sec}s\nPersistent=true\n\n"
        f"[Install]\nWantedBy=timers.target\n"
    )


def run_self_test() -> int:
    sample_manifest = {
        "id": "commons.doc_watcher",
        "name": "Shared Commons Doc Watcher",
        "entrypoint": {
            "command": ["/usr/bin/python3", "/opt/agent/watch_doc_once.py"],
            "working_dir": "/opt/agent",
            "timeout_seconds": 30,
        },
        "schedule": {
            "type": "interval",
            "interval_seconds": 60,
            "launchd_label": "com.agent.commons.doc_watcher",
            "systemd_unit": "agent-commons-doc-watcher",
        },
    }
    plist_xml = compile_launchd_plist(sample_manifest)
    timer_ini = compile_systemd_timer(sample_manifest)
    ok = "com.agent.commons.doc_watcher" in plist_xml and "OnUnitActiveSec=60s" in timer_ini
    print(json.dumps({"self_test_ok": ok, "daemon_id": sample_manifest["id"]}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compile declarative daemon manifest to launchd/systemd")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    sys.exit(run_self_test())

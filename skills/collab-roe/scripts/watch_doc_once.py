#!/usr/bin/env python3
"""
watch_doc_once.py — Background daemon watcher for a shared Google Doc.

Loads the persisted baseline snapshot (or captures one on first run) and polls
every POLL_INTERVAL_SECONDS. When any edit, inline callout, new tab, or comment
is detected, writes the diff report to /home/antigravity/docs/andrew_latest_diff.md
and ~/.gemini/state/andrew_latest_diff.md.
"""

import difflib
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

DOC_ID = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("WATCH_DOC_ID", "{{GOOGLE_DOC_ID}}")
POLL_INTERVAL_SECONDS = int(sys.argv[2]) if len(sys.argv) > 2 else 60
STATE_DIR = os.path.expanduser("~/.gemini/state")
os.makedirs(STATE_DIR, exist_ok=True)
BASELINE_PATH = os.path.join(STATE_DIR, f"doc_watch_baseline_{DOC_ID}.json")
DIFF_REPORT_STATE = os.path.join(STATE_DIR, "andrew_latest_diff.md")
DIFF_REPORT_WORKSPACE = "/home/antigravity/docs/andrew_latest_diff.md"


def run_gdocs(args):
    res = subprocess.run(
        ["gdocs"] + args,
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        return None, res.stderr.strip()
    return res.stdout, None


def fetch_snapshot(doc_id):
    tabs_out, _ = run_gdocs(["readonly", "list-tabs", doc_id, "--json"])
    tab_ids = ["t.0"]
    if tabs_out:
        try:
            tabs_data = json.loads(tabs_out)
            if isinstance(tabs_data, list) and tabs_data:
                tab_ids = [t.get("tabId", "t.0") for t in tabs_data if t.get("tabId")]
        except Exception:
            pass

    tabs_content = {}
    for tid in tab_ids:
        read_out, _ = run_gdocs(["readonly", "read", doc_id, "--tab", tid])
        tabs_content[tid] = read_out or ""

    comments_out, _ = run_gdocs(["readonly", "list-comments", doc_id, "--json"])
    comments_raw = comments_out or "[]"

    payload = {
        "tab_ids": tab_ids,
        "tabs_content": tabs_content,
        "comments_raw": comments_raw,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    payload["digest"] = digest
    payload["captured_at"] = datetime.now(timezone.utc).isoformat()
    return payload


def main():
    if os.path.exists(BASELINE_PATH):
        with open(BASELINE_PATH, "r", encoding="utf-8") as f:
            initial = json.load(f)
        print(
            f"[watch_doc] Loaded existing baseline digest={initial['digest'][:12]} from {initial['captured_at']}",
            flush=True,
        )
    else:
        initial = fetch_snapshot(DOC_ID)
        with open(BASELINE_PATH, "w", encoding="utf-8") as f:
            json.dump(initial, f, indent=2)
        print(
            f"[watch_doc] Captured new baseline digest={initial['digest'][:12]} at {initial['captured_at']}",
            flush=True,
        )

    while True:
        current = fetch_snapshot(DOC_ID)
        if any(current["tabs_content"].values()) and current["digest"] != initial["digest"]:
            lines = [
                f"# Change Detected on Andrew's Proposal Doc (`{DOC_ID}`)",
                f"- **Baseline Captured At:** `{initial['captured_at']}` (`{initial['digest'][:12]}`)",
                f"- **Change Detected At:** `{current['captured_at']}` (`{current['digest'][:12]}`)",
                "",
            ]
            all_tabs = sorted(set(initial["tab_ids"]) | set(current["tab_ids"]))
            for tid in all_tabs:
                old_lines = initial["tabs_content"].get(tid, "").splitlines(keepends=True)
                new_lines = current["tabs_content"].get(tid, "").splitlines(keepends=True)
                if old_lines != new_lines:
                    diff = "".join(
                        difflib.unified_diff(
                            old_lines,
                            new_lines,
                            fromfile=f"{tid}@baseline",
                            tofile=f"{tid}@current",
                            n=3,
                        )
                    )
                    lines.append(f"## Diff in Tab `{tid}`\n```diff\n{diff}\n```\n")

            if initial["comments_raw"] != current["comments_raw"]:
                lines.append(f"## Updated Comments JSON\n```json\n{current['comments_raw']}\n```\n")

            report = "\n".join(lines)
            os.makedirs(os.path.dirname(DIFF_REPORT_WORKSPACE), exist_ok=True)
            with open(DIFF_REPORT_STATE, "w", encoding="utf-8") as f:
                f.write(report)
            with open(DIFF_REPORT_WORKSPACE, "w", encoding="utf-8") as f:
                f.write(report)

            print(report, flush=True)
            initial = current
            with open(BASELINE_PATH, "w", encoding="utf-8") as f:
                json.dump(current, f, indent=2)

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()

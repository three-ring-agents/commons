# Playbook: Multi-Host Infrastructure, Monitoring, Logging & Self-Healing (`oldmacmini` Stack)

**Category:** `Infrastructure / Host Monitoring / Telemetry & Self-Healing`  
**Original Concept:** `Andrew` • **Field Execution & Postmortem:** `Andrew & Jon`  
**Peer Overrides:** `profiles/macos-catalina-legacy/` and `profiles/macos-proxmox-unifi/`

---

## 1. Architectural Intent & Invariants

Provides a production-tested blueprint for running an always-on, low-power macOS home server (`oldmacmini` / `2012-Mini` @ `{{OLDMACMINI_LAN_IP}}`) acting as the 24/7 background automation anchor, smart home telemetry gateway, and local Apple services bridge alongside a primary operator workstation (`{{PRIMARY_WORKSTATION_HOST}}`).

This playbook standardizes the multi-host supervision model, capability heartbeats, log rotation/disk preservation, system pressure guards, and the 3-tier self-healing escalation ladder.

### Architectural Invariants

- **Invariant 1 (Dual-User Privilege Separation):** Background daemons run under a dedicated, unprivileged service account (`{{DAEMON_USER}}`) separate from the primary operator desktop account (`{{PRIMARY_USER}}`). Personal desktop locks or user logouts do not terminate the service daemon.
- **Invariant 2 (Full Disk Access via Terminal Launcher — Local TCC/FDA Stores Only):** In macOS (Catalina through Sonoma), direct `launchd` LaunchAgents cannot reliably retain Full Disk Access (FDA) across OS updates when invoking `/usr/bin/python3` directly. Whenever a daemon reads local macOS TCC/FDA-protected SQLite stores (such as Apple Messages / iMessage `~/Library/Messages/chat.db`), the LaunchAgent must invoke `/usr/bin/open -a Terminal <script>.command` with `KeepAlive=false` and `RunAtLoad=true` to inherit `Terminal.app`'s persistent TCC/FDA grant, preventing `chat.db (authorization denied)` lockouts. *(Scope Note: Pure HTTPS/OAuth chat & comms daemons—Google Chat, Gmail, Pub/Sub, Telegram—do not require FDA and should run as standard headless `launchd` / `systemd` workers without `Terminal.app`.)*
- **Invariant 3 (Immortal Guardian Supervisor & Hot Reload):** An out-of-process Guardian supervisor (`PID` tracking) monitors the worker daemon. When configuration or prompt logic changes, in-process hot reload (`importlib.reload`) refreshes bot logic in RAM without dropping active mTLS sockets or bouncing the process.
- **Invariant 4 (Bounded Log Capacities & 1-Tap Disk Preservation):** Dedicated servers with legacy SSDs must protect against log file runaway. All daemon log files are strictly capped at 8 MB (`LOG_MAX_BYTES = 8 * 1024 * 1024`). A deterministic disk reclamation routine (`clean_oldmacmini_disk_space`) prunes `.log.*` archives, clears stale Xcode build caches (`DerivedData`), and scrubs staging bundles whenever free disk space approaches ~15 GB.
- **Invariant 5 (System Pressure & Thread Exhaustion Guard):** Monitors macOS kernel threads for known Apple daemon leaks—specifically tracking `storagekitd` thread consumption against its 4096-thread kernel ceiling—alongside total process counts and active console sessions.
- **Invariant 6 (3-Tier Self-Healing & Off-Box Dead-Man's Switch):**
  - *Tier 1a (In-Process Healing):* Exponential backoff on database locks and automatic file permission normalization (`0660`) across multi-user cache directories.
  - *Tier 1b (Local Machine Watchdog):* Local LaunchAgent watchdog (`kit_host_monitor.py` / `mac_mini_heartbeat.sh`) with native macOS notifications and process revival.
  - *Tier 2 (Mobile Cockpit & FaceID Action Vault):* Live mobile telemetry payload (`build_unified_infrastructure_cockpit()`) synthesized into iOS endpoints (`POST /v1/ios/vault/infrastructure`) with 1-tap remote maintenance actions (`clean_oldmacmini_disk`).
  - *Tier 3 (Off-Box Cloud Dead-Man's Switch — 2 Peer Reference Patterns):*
    - **Pattern 3A (`profiles/macos-catalina-legacy/` — Google Drive + Google Apps Script):** Google Apps Script (`dead_mans_switch_apps_script.gs`) running in Google Workspace on a 5-minute time trigger, monitoring heartbeat timestamps synced to Google Drive (`mac_mini_health.json`); if 3 consecutive strikes occur (>15 minutes stale), it sends an out-of-band email/SMS alert.
    - **Pattern 3B (`profiles/macos-proxmox-unifi/cloudflare_worker_dead_mans_switch.js` — Cloudflare Workers Cron Trigger + KV):** For households already using Cloudflare (`$0.00/mo` Free Tier: 100k req/day + 1,000 KV writes/day + `*/5 * * * *` Cron Triggers), hosts push an `HMAC-SHA256`-signed JSON heartbeat every 5 minutes (`288` writes/day per host) to a Cloudflare Worker + KV namespace. Runs in an **orthogonal control plane** outside Google Workspace/GCP, eliminates OAuth/RAPT token expiry false alarms and Google Drive revision churn, verifies both inbound host heartbeats and external Cloudflare Tunnel reachability from the edge, and pages via VoIP.ms SMS + webhook.

### Runtime Config Keys (`~/.gemini/state/config.json`)

```json
{
  "local_hosts": {
    "primary_workstation": "{{PRIMARY_WORKSTATION_HOST}}",
    "dedicated_server": "oldmacmini",
    "server_lan_ip": "{{OLDMACMINI_LAN_IP}}"
  },
  "monitoring": {
    "stale_heartbeat_threshold_mins": 20.0,
    "log_max_bytes": 8388608,
    "disk_warning_threshold_gb": 15.0,
    "storagekitd_thread_ceiling": 4096
  }
}
```

---

## 2. Pitfalls & Field Postmortems ("What Broke / Ordering Gotchas")

### Gotcha 1 (LaunchAgent `KeepAlive=true` Cascading Crash Storm)
- **The Trap:** Setting `<key>KeepAlive</key><true/>` in `~/Library/LaunchAgents/com.<service>.plist` while invoking a Python script that requires TCC permissions (e.g. `chat.db`).
- **What Broke:** If permissions are revoked during an OS update or machine reboot, the Python process exits `1` immediately. `launchd` restarts it every 2 seconds, creating a runaway process storm that writes thousands of error lines per minute, exhausting disk I/O and filling the log partition within hours.
- **The Solution:** Always set `KeepAlive=false` and `RunAtLoad=true`. Let the LaunchAgent launch via `/usr/bin/open -a Terminal relaunch_daemon.command`, and use an internal Python loop with exponential backoff and a Guardian PID file to manage process resilience.

### Gotcha 2 (macOS `storagekitd` 4096-Thread Exhaustion Bug)
- **The Trap:** Leaving older macOS installations (2012–2018 Intel Mac Minis) running headless for 30+ days without monitoring system threads.
- **What Broke:** Apple's `storagekitd` daemon periodically leaks worker threads when external USB storage or APFS snapshots are queried. Once `storagekitd` hits 4096 threads, macOS refuses to spawn new POSIX threads or processes (`fork: Resource temporarily unavailable`), causing SSH and daemon health checks to hang indefinitely.
- **The Solution:** Added active thread inspection (`ps -M <PID>` or `taskinfo`) inside `inspect_system_pressure()`. If `storagekitd` exceeds 1000 threads, an early warning is surfaced to the infrastructure cockpit so the process can be safely restarted (`killall -9 storagekitd`) before hitting the hard 4096 ceiling.

### Gotcha 3 (Cross-User Cache Permission Denied `[Errno 13]`)
- **The Trap:** When user A (`{{PRIMARY_USER}}`) runs a data ingestion cron job that writes shared cache files (e.g. `weather_cache.json`, `home_status_cache.json`), default macOS `umask` (`022`) creates files with `rw-r--r--`.
- **What Broke:** User B (`{{DAEMON_USER}}`, the daemon) attempts to update the cache and crashes with `PermissionError: [Errno 13] Permission denied`.
- **The Solution:** The cross-user health watchdog inspects all files in `cache/` on every cycle and auto-heals permissions to `0660` (`chmod 660`) and directory ownership, ensuring collaborative multi-user access without requiring `sudo`.

### Gotcha 4 (Off-Box Dead-Man's Switch vs. On-Box Watchdogs)
- **The Trap:** Relying solely on local cron or LaunchAgent scripts to send notifications when an always-on host fails.
- **What Broke:** When a kernel panic, power outage, or home router freeze occurs, the on-box watchdog dies with the host and never fires an alert.
- **The Solution:** Pair local Tier 1 watchdogs with an off-box cloud Dead-Man's Switch (**Pattern 3A**: `mac_mini_health.json` synced to Google Drive and monitored every 5 minutes by `dead_mans_switch_apps_script.gs`; **Pattern 3B**: `HMAC-SHA256`-signed heartbeats pushed every 5 minutes to a Cloudflare Worker + KV namespace monitored by a `*/5 * * * *` Cron Trigger).

### Gotcha 5 (Cloudflare Workers + KV `Pattern 3B` Headless REST API Provisioning Quirks)
- **Gotcha 5A (`code: 10063` Cron Trigger Subdomain Prerequisite):** Even when routing traffic exclusively through a custom domain (`dms.<domain>/*`), Cloudflare's `PUT /accounts/<id>/workers/scripts/<name>/schedules` API rejects Cron Triggers with `code: 10063` (`workers.api.error.Triggering_without_subdomain`) unless the account's `workers.dev` subdomain is registered (`PUT /accounts/<id>/workers/subdomain`) and enabled on the script (`POST /accounts/<id>/workers/scripts/<name>/subdomain` with `{"enabled": true}`) first.
- **Gotcha 5B (Originless Custom Domain Route Needs Both Proxied `A 192.0.2.1` + `AAAA 100::`):** Cloudflare documentation recommends creating only a proxied `AAAA 100::` dummy record for originless Worker custom domain routes. On IPv4-only home LANs, DNS `A` queries return `NODATA`, causing Python `urllib`/`curl` clients to fail name resolution until a proxied RFC 5737 `A 192.0.2.1` record is paired alongside `AAAA 100::`.
- **Gotcha 5C (V8 Block-Comment Termination on Cron Expressions):** Writing a raw cron expression (`*/5 * * * *`) inside a JavaScript `/** ... */` JSDoc header prematurely closes the block comment at `*/`, causing V8 ES module upload (`PUT /workers/scripts/<name>`) to fail with `Uncaught SyntaxError: Unexpected token '*'`.
- **Gotcha 5D (Zero-Subprocess `storagekitd` Mach Thread Counting via `libproc.dylib`):** Instead of spawning `ps -M <pid> | wc -l` every heartbeat tick, calling `libproc.proc_pidinfo(pid, PROC_PIDTASKINFO=4)` via Python `ctypes` reads Mach `pti_threadnum` in-process in `<0.1 ms` with zero child-process overhead (see `profiles/macos-proxmox-unifi/deploy_cloudflare_dms.py`).

---

## 3. Pre-Flight & Post-Flight Verification Probes

### Pre-Flight Verification Probe

Before making infrastructure or LaunchAgent modifications, verify current host telemetry, socket bindings, and TCC readability:

```bash
# 1. Verify Full Disk Access and chat.db readability
sqlite3 "$HOME/Library/Messages/chat.db" "SELECT count(*) FROM message;" 2>/dev/null && echo "✓ chat.db accessible (FDA OK)" || echo "✗ chat.db DENIED"

# 2. Inspect active daemon ports and background processes
lsof -i :8765 -i :8766 -i :8767 || true
pgrep -fl "alvin|imessage|kit" || true

# 3. Check storagekitd thread consumption
SK_PID=$(pgrep storagekitd || true)
if [ -n "$SK_PID" ]; then
  THREAD_COUNT=$(ps -M $SK_PID | wc -l)
  echo "storagekitd PID $SK_PID threads: $THREAD_COUNT / 4096"
fi
```

### Post-Flight Verification Probe

Run the built-in deterministic verification suite across both local host and cloud state models:

```bash
# 1. Execute local telemetry collector and generate scannable report
python3 ~/.gemini/state/skills/kit/scripts/kit_host_monitor.py collect-local

# 2. Inspect generated multi-host Markdown report
cat ~/.gemini/state/kit/MAC_MINI_HEALTH.md

# 3. Validate zero-finding compliance in Stage 1 Redaction Gate
python3 ~/.gemini/commons/skills/sync-commons/scripts/redact_check.py scan
```

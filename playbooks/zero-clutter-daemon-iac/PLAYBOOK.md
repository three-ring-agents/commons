# Playbook: Turnkey Multi-Environment Daemon Infrastructure-as-Code (`launchd` / `systemd` / Cloud Run) & Zero-Clutter Crons

**Category:** `Infrastructure / Background Daemons / Cross-Conversation Coordination`  
**Commons Namespace:** `three-ring-agents/commons/playbooks/zero-clutter-daemon-iac`  
**Peer Overrides:** Optional `profiles/<archetype>/ or ~/.gemini/mesh/profiles/<archetype>/`

---

## 1. Our Setup

### Architectural Intent & Invariants

Eliminates Antigravity UI clutter and permanent `Running`-state lockups caused by in-conversation `schedule` crons or background `sleep` loops. Every recurring watcher, sync worker, and health probe runs as an **OS-level or container-level headless daemon** compiled deterministically from a single declarative `manifest.json` (`registry.d/*.json`).

Our setup enforces five operational invariants across all registered background jobs:

- **Invariant 1 (Zero-Clutter Interactive Sessions):** Primary interactive conversations and child subagents never hold open recurring `schedule` crons. Background polling runs externally via OS schedulers (`launchd` on macOS, `systemd` on Linux/Proxmox LXCs, or Cloud Run Jobs) and wakes an interactive thread **only** when a high-signal state transition or anomaly requires human/agent review.
- **Invariant 2 (Single Declarative `manifest.json` $\to$ Multi-Target IaC Compiler):** Each daemon declares its `id`, `entrypoint`, `schedule`, `resources.code_paths`, `resources.state_stores`, `network_dependencies`, and `max_consecutive_failures` in `manifest.json`. The IaC compiler emits:
  1. **macOS `launchd` `.plist`:** `ProcessType=Background`, `Nice=10`, `AbandonProcessGroup=false`, explicit `WorkingDirectory`, and absolute runtime binary paths.
  2. **Linux / Proxmox LXC & ARM64 `systemd` `.service` + `.timer`:** Hardened unit files with `NoNewPrivileges=true`, `PrivateTmp=true`, `ProtectSystem=strict`, and `ReadWritePaths` scoped strictly to the daemon's state directory.
  3. **Cloud Run Jobs Manifest:** Portable container job definitions for cloud-compatible workers.
- **Invariant 3 (Portability Matrix Filtering — `DE-IAC-01`):** Hardware- or host-coupled daemons that require local macOS `launchctl`/disk access or Layer-2 LAN/VLAN broadcast reachability (`192.0.2.0/24` / `<LAN_SUBNET>`) are explicitly tagged in `PORTABILITY_MATRIX.json` and excluded from blind Cloud Run deployment.
- **Invariant 4 (Automatic Release Rollback on 3 Consecutive Failures):** Every daemon maintains versioned release snapshots (`active_release` vs. `previous_release`). If `active_release` fails 3 consecutive scheduled ticks, the supervisor automatically rolls back to `previous_release` and records a structured alert in `daemon_state.db`.
- **Invariant 5 (Cross-Conversation Edit Leases & SQLite `0600` WAL):** Before any interactive session edits a scheduled script or shared SQLite state store, it inspects blast radius (`daemon_inspect_impact`) and acquires a time-bounded `WORKSPACE_EDIT` or `MAINTENANCE_PAUSE` lease in `daemon_state.db` (`PRAGMA journal_mode=WAL`, `0600` permissions).

#### Runtime Config Keys (`~/.gemini/state/config.json`)

```json
{
  "daemon_iac": {
    "registry_dir": "~/.gemini/state/daemon/registry.d",
    "generated_dir": "~/.gemini/state/daemon/iac/generated",
    "state_db": "~/.gemini/state/daemon/state/daemon_state.db",
    "portability_matrix": "~/.gemini/state/daemon/iac/generated/PORTABILITY_MATRIX.json",
    "dashboard_bind_host": "127.0.0.1",
    "dashboard_bind_port": 8780
  },
  "secrets": {
    "daemon_vault_ro": "op://Agent-<User>/Vault-RO/service_token"
  }
}
```

### Pitfalls & Field Postmortems ("What Broke / Ordering Gotchas")

- **Gotcha 1 (In-Conversation `schedule` Crons Lock UI Status as `Running`):** Running a 5-minute `schedule` cron inside a primary conversation keeps the conversation permanently marked `Running` in the sidebar and appends hundreds of no-op turns to `transcript.jsonl`. Offloading recurring ticks to OS-level `launchd`/`systemd` units keeps interactive threads 100% `IDLE` until an actionable delta occurs.
- **Gotcha 2 (Deploying Host- or Layer-2-Coupled Daemons to Cloud Run — `DE-IAC-01`):** Attempting to deploy daemons that inspect local macOS host posture, local SQLite transcripts, or Layer-2 ARP/mDNS tables (`<LAN_SUBNET>`) to serverless Cloud Run containers fails at runtime because they lack local host disk and Layer-2 adjacency. Always gate target environments via `PORTABILITY_MATRIX.json`.
- **Gotcha 3 (macOS `launchd` Environment Stripping & `KeepAlive=true` Crash Storms):** `launchd` does not inherit interactive shell `PATH` variables, and setting `KeepAlive=true` on a failing script spawns a 2-second restart loop that fills disk logs. Use calendar/interval triggers (`StartCalendarInterval` / `StartInterval`) with exponential backoff, bounded log rotation (`8 MB` cap), and explicit binary paths.
- **Gotcha 4 (Concurrent SQLite Access Without `WAL` + `immutable=1` Read Fallback):** When a background daemon writes to a SQLite database while a sandboxed read-only worker queries it, missing `-shm` write permissions or default journal modes cause `database is locked` errors. Always initialize state stores with `PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;` (`0600`) and use `immutable=1` + `PRAGMA temp_store=MEMORY` for read-only analytic readers.

### Pre-Flight & Post-Flight Verification Probes

```bash
# Pre-Flight Probe 1: Validate daemon manifest schemas & dry-run multi-target IaC compilation
python3 ~/.gemini/commons/playbooks/zero-clutter-daemon-iac/scripts/compile_daemon_iac.py --self-test

# Pre-Flight Probe 2: Verify 3-Stage Outbound Redaction Gate on playbook files
python3 ~/.gemini/commons/skills/redact-gate/scripts/scrub.py --check ~/.gemini/commons/playbooks/zero-clutter-daemon-iac

# Post-Flight Probe 1: Verify Stage 1 Redaction Gate cleanliness across Commons
python3 ~/.gemini/commons/skills/sync-commons/scripts/redact_check.py scan

# Post-Flight Probe 2: Verify local daemon dashboard binds strictly to 127.0.0.1 (never 0.0.0.0)
lsof -nP -iTCP:8780 -sTCP:LISTEN || true
```

---

## 2. Other Options

When selecting a scheduling and supervision substrate for household or homelab automation (`profiles/<archetype>/`), consider these alternatives:

1. **Go-First Single-Binary Turnkey Daemon SDK (`CGO_ENABLED=0` + `internal/daemonsdk`):**
   - *Pros:* Compiles into a zero-dependency static binary with built-in heartbeat reporting, structured JSON logging, atomic file writes, and `127.0.0.1`-enforced health endpoints; eliminates Python virtualenv drift across macOS and Debian LXC hosts.
   - *Cons:* Slightly higher upfront compile step than a single-file Python script for rapid prototyping or heavy SQLite FTS5 / MIME parsing workloads.
2. **Dedicated Proxmox Debian LXC (`systemd` Timers) vs. Always-On macOS Host (`launchd`):**
   - *Pros:* Moving portable network/API daemons onto an isolated Proxmox LXC (`systemd`) frees workstation RAM, isolates container filesystem blast radius, and avoids macOS TCC/Keychain modal prompts.
   - *Cons:* Daemons requiring macOS-specific frameworks (`launchctl`, local IDE transcripts, or Apple Bridge integrations) must remain pinned to the macOS host (`macos_launchd` in `PORTABILITY_MATRIX.json`).
3. **Peer Cron-Host Conversation (`IsDaemon: true` Background Agent Thread):**
   - *Pros:* Useful when a recurring task genuinely requires multi-turn LLM reasoning and native Antigravity tool access on every tick.
   - *Cons:* Consumes rolling 5-hour model quota on every wakeup; deterministic Go/Python OS daemons that only wake an agent on state transitions reduce steady-state token burn to `$0.00/mo`.
4. **Off-Box Cloud Dead-Man's Switch (Google Apps Script Pattern 3A / Cloudflare Workers Cron Trigger + KV Pattern 3B):**
   - *Pros:* Continues alerting via email/SMS/webhook even if home power, ISP WAN links, or the local hypervisor go completely offline; Pattern 3B runs on Cloudflare's `$0.00/mo` Free Tier (`*/5 * * * *` Cron Trigger + KV) in an orthogonal control plane outside Google Workspace/GCP.
   - *Cons:* Cannot directly inspect internal `<LAN_SUBNET>` devices without a heartbeat pushed to KV or synced to Drive; best used as Tier 3 off-box supervision paired with local `launchd`/`systemd` Tier 1 watchdogs.

---

## 3. Suggested Reading

- **OS Service Hardening & Supervision References:**
  - `systemd.exec(5)` & `systemd.timer(5)` — Linux service sandboxing (`ProtectSystem=strict`, `NoNewPrivileges=true`, `PrivateTmp=true`).
  - `launchd.plist(5)` — macOS daemon scheduling, `ProcessType=Background`, and resource limits.
  - SQLite Documentation — *Write-Ahead Logging (`WAL`)* and URI `immutable=1` read-only concurrency patterns.
- **Related Commons Playbooks & Skills:**
  - `playbooks/zero-clutter-daemon-iac/PLAYBOOK.md` — Reference IaC compiler (`scripts/compile_daemon_iac.py`).
  - `playbooks/host-infrastructure-and-telemetry/PLAYBOOK.md` — Multi-host supervision, `storagekitd` thread guard, and 3-tier self-healing ladder.
  - `playbooks/plan-bound-mpa-and-secret-isolation/PLAYBOOK.md` — Cross-conversation edit leases and Plan-Bound MPA governance.

# Playbook: `<Title>`

**Category:** `<Network / Proxmox / Home Automation / Security>`  
**Original Concept:** `<Andrew / Jon>` • **Field Execution & Postmortem:** `<Jon / Andrew>`  
**Peer Overrides:** Optional `variants/andrew/` and `variants/jon/`

---

## 1. Architectural Intent & Invariants

State the security and operational invariants that must hold true regardless of hardware, firmware version, or local subnet numbering:

- **Invariant 1:** ...
- **Invariant 2:** ...
- **Runtime Config Keys (`~/.gemini/state/config.json`):** List the `config.json` keys or `op://Agent-<User>/...` secret pointers consumed by this playbook.

---

## 2. Pitfalls & Field Postmortems ("What Broke / Ordering Gotchas")

Document real-world failures, rule-ordering traps, or API quirks encountered in production so the receiving agent avoids them:

- **Gotcha 1 (Ordering / Lockout):** ...
- **Gotcha 2 (Firmware / API Quirk):** ...

---

## 3. Pre-Flight & Post-Flight Verification Probes

Deterministic commands the agent must run before and after applying changes:

```bash
# Pre-Flight Probe: Verify reachability and backup current state
...

# Post-Flight Probe: Verify all invariants hold
...
```

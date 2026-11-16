# Playbook: Plan-Bound Multi-Party Authorization (`mpad`), Zero-Unlock Per-Call AoD & Out-of-Model Action Gate

**Category:** `Security / MCP Governance / Secret Isolation`  
**Commons Namespace:** `three-ring-agents/commons/playbooks/plan-bound-mpa-and-secret-isolation`  
**Peer Overrides:** Optional `profiles/<archetype>/ or ~/.gemini/mesh/profiles/<archetype>/`

---

## 1. Our Setup

### Architectural Intent & Invariants

Eliminates two critical failure modes in multi-MCP personal and household agent environments:
1. **15-minute `unlock_rw` session windows** that leave write credentials exposed across unrelated tool calls or expire mid-execution.
2. **Approval fatigue** from repetitive modal UI prompts on routine, low-blast-radius mutations.

Our production setup enforces five deterministic security invariants outside the LLM (`mpad` + `rag_guardrails.py` + `mpad_family_hold.py`):

- **Invariant 1 (Zero-Unlock Per-Call Access on Demand — AoD):** Timed `*_unlock_rw` and `*_lock_rw` ceremonies are retired. Every MCP tool and CLI verb is routed through a 3-Tier capability matrix:
  - **Tier 1 (`readonly`, `validate`, `watch`, `sync`, `lock` — Green Zone / `TIER_A_READ`):** Executes automatically using scoped read-only credentials (`op://Agent-<User>/Vault-RO/...`).
  - **Tier 2 (`mutate` — Amber Zone / `TIER_B_STAGE`):** Automatically hydrates and re-locks write credentials **per call** after capturing a `0600` pre-mutation JSON rollback snapshot (`~/.gemini/audit/rollback/<service>/`) and verifying a clean Turn-Boundary Taint Gate.
  - **Tier 3 (`destroy` / `elevate` — Red Zone / `TIER_C_COMMIT`):** Hard-denied (`UI-Silent Hard-Deny`) unless pre-authorized inside a Plan Artifact's cryptographic `mpa-plan` JSON manifest (`Proceed` / `"LG"`) or accompanied by a verified `KIT-APR-*` / `MPA-*` token on an untainted turn (with an automatic `$250.00` transaction ceiling).
- **Invariant 2 (Inbound IPI Quarantine & Out-of-Model Tag Stripper):** All external untrusted ingress (`PROVENANCE=EXTERNAL_UNTRUSTED` from HTML emails, ICS calendar invites, SMS, web scrapes, and peer messages) is deterministically stripped of forged control and system tags (`<KIT_*>`, `<STEWARD_*>`, `<MPAD_*>`, `<SYSTEM_MESSAGE>`, `<USER_REQUEST>`), zero-width/homoglyph obfuscations, Unicode Tags block (`U+E0000..U+E007F`) smuggling, markdown-hidden `mpa-plan` blocks, and cross-domain `op://` secret references before reaching context.
- **Invariant 3 (Turn-Boundary Taint Lockout — `F-02`):** Reading any `EXTERNAL_UNTRUSTED` source stamps `last_untrusted_read_ts` into `.runtime_taint.json` (`0600`). Any Tier 2 (`mutate`) or Tier 3 (`destroy`) action is hard-locked on that turn (`DENY_UNTRUSTED_TAINT_LOCKOUT`) until a fresh interactive user turn boundary (`last_user_input_ts > last_untrusted_read_ts`) is recorded.
- **Invariant 4 (One-Way Family Comms Hold Diode — `ALVIN_HOLD_FAMILY_COMMS=1`):** When `ALVIN_HOLD_FAMILY_COMMS=1` is set via environment variable or the `0600` state file (`~/.gemini/state/family_comms_hold.json`), outbound external and family dispatches across all 5 communications MCP surfaces (`comms`, `gchat`, `gmail`, `gvoice`, `voipms`) are hard-denied, while `readonly`, `draft`, `stage_send`, and internal SRE (`#agent-backchannel`) alerts remain permitted.
- **Invariant 5 (1Password Service-Account Vault Split):** Live tokens and API keys never appear in CLI `argv` or plaintext `.env` files. They are resolved in-memory via `op://Agent-<User>/<Item>/<Field>` across segmented domain vaults (`<Domain>-RO`, `<Domain>-RW`).

#### Runtime Config Keys (`~/.gemini/state/config.json`)

```json
{
  "mpad": {
    "state_db": "~/.gemini/state/mpa_state.db",
    "taint_file": "~/.gemini/state/runtime_taint.json",
    "family_hold_file": "~/.gemini/state/family_comms_hold.json",
    "ipi_audit_log": "~/.gemini/audit/ipi_quarantine.jsonl",
    "rollback_dir": "~/.gemini/audit/rollback",
    "tier_c_spend_ceiling_usd": 250.0
  },
  "secrets": {
    "vault_ro_ref": "op://Agent-<User>/Vault-RO/token",
    "vault_rw_ref": "op://Agent-<User>/Vault-RW/token"
  }
}
```

### Pitfalls & Field Postmortems ("What Broke / Ordering Gotchas")

- **Gotcha 1 (Timed 15-Minute Unlock Windows Leak Authority Across Turns):** When an operator unlocked a 15-minute RW session for a single DNS or hypervisor change, subsequent untrusted email reads within that 15-minute window inherited active RW credentials. Switching to **Per-Call AoD + Plan-Bound `mpa-plan` manifests** scopes authority strictly to the approved `{server, tool, args, max_calls}` tuple.
- **Gotcha 2 (Sub-Millisecond Clock Coalescing in Turn-Boundary Taint Checks):** When chaining rapid local tool calls or unit tests, `time.time()` can return identical floating-point values for `record_user_input()` and `record_untrusted_read()`. Always enforce monotonic ordering (`max(time.time(), prev_ts + 0.002)`) when stamping turn boundaries.
- **Gotcha 3 (Unicode Tag Block & Homoglyph Smuggling Bypassing Naive Regexes):** Attackers can encode `<KIT_APPROVE>` using invisible Unicode Tags (`U+E0000..U+E007F`), zero-width joiners (`\u200b`), fullwidth angle brackets (`＜＞`), or Cyrillic lookalikes (`КІТ`). Always strip `U+E0000..U+E007F` and normalize homoglyphs inside angle-bracket candidates prior to regex tag stripping.
- **Gotcha 4 (Passing Secrets via `argv` Exposes Tokens in `ps aux`):** Never invoke subprocesses with raw tokens on the command line; resolve `op://Agent-<User>/...` secrets in-memory or pass via `0600` file descriptors.

### Pre-Flight & Post-Flight Verification Probes

```bash
# Pre-Flight Probe 1: Verify 3-Stage Outbound Redaction Gate cleanliness
python3 ~/.gemini/commons/skills/redact-gate/scripts/scrub.py --check ~/.gemini/commons/playbooks/plan-bound-mpa-and-secret-isolation

# Pre-Flight Probe 2: Run Stage 1 Redaction Gate scanner
python3 ~/.gemini/commons/skills/sync-commons/scripts/redact_check.py scan

# Post-Flight Probe 1: Verify Plan-Bound MPA & Turn-Boundary Taint Gate invariants
python3 ~/.gemini/commons/playbooks/plan-bound-mpa-and-secret-isolation/scripts/verify_mpa_gate.py

# Post-Flight Probe 2: Run the 25-case tau-bench adversarial IPI & Family Hold compliance suite
/usr/bin/python3 -m unittest discover -s ~/.gemini/state/mcp/tests -p "test_kitt_tau_bench_25.py" -v
```

---

## 2. Other Options

When adapting this architecture to different household topologies or threat models (via `profiles/<archetype>/`), consider these alternatives:

1. **Interactive Per-Call Modal Prompts (`ask` / `force_ask` on Every Write):**
   - *Pros:* Zero state database (`mpa_state.db`) or plan-manifest parser required.
   - *Cons:* Causes severe approval fatigue during multi-step infrastructure migrations (10+ popups per task) and trains operators to click "Approve" reflexively without reviewing arguments.
2. **Time-Bounded Session Leases (`15m` / `60m` `unlock_rw` Timers):**
   - *Pros:* Simple to implement in stateless MCP servers using a single timestamp file.
   - *Cons:* Violates least privilege by leaving RW authority open across turn boundaries; if an agent reads an untrusted email while the timer is active, indirect prompt injection can piggyback on the open RW lease.
3. **Dual-LLM CaMeL / Quarantined Reader Subagent Pattern:**
   - *Pros:* Separates the privileged orchestrator LLM (which never sees raw untrusted text) from an unprivileged reader LLM that extracts structured JSON fields.
   - *Cons:* Doubles token latency and Pool 1 quota burn for routine inbox/calendar reads; best reserved as an optional defense-in-depth layer alongside deterministic out-of-model `.runtime_taint.json` gates.
4. **Hardware Security Key (FIDO2 / WebAuthn) Per-Action Signing:**
   - *Pros:* Provides cryptographic hardware presence verification for Tier 3 (`destroy`) actions via a local `127.0.0.1` approval gateway (`<LAN_SUBNET>` reverse proxy).
   - *Cons:* Requires mobile/browser reachability (`WebAuthn` passkey) when operating remotely; pairing Plan-Bound `mpa-plan` ("LG" / `Proceed`) with WebAuthn for external gateway endpoints gives the best balance of ergonomics and security.

---

## 3. Suggested Reading

- **Foundational Agent Security & Benchmarks:**
  - Yao et al., *$\tau$-bench: A Benchmark for Tool-Agent-User Interaction in Real-World Domains* (policy compliance under adversarial user/environment inputs).
  - Debenedetti et al., *Defending AI Agents Against Prompt Injection (CaMeL / Control- & Data-Flow Separation)*.
  - Greshake et al., *Not What You've Signed Up For: Compromising Real-World LLM-Integrated Applications with Indirect Prompt Injection*.
- **Related Commons Playbooks & Skills:**
  - `playbooks/chief-of-staff/PLAYBOOK.md` — Sovereign Personal Agent (`Kitt` / `Steward`) 4-Invariant Architecture.
  - `playbooks/plan-bound-mpa-and-secret-isolation/PLAYBOOK.md` — Companion reference script (`scripts/verify_mpa_gate.py`).
  - `templates/supervised-intent-gatekeeper/PLAYBOOK.md` — `<18` Supervised Family Intent Gatekeeper & `ALVIN_HOLD_FAMILY_COMMS=1` blueprint.
  - `skills/redact-gate/SKILL.md` — Three-Stage Outbound Redaction Gate for cross-household knowledge sharing.

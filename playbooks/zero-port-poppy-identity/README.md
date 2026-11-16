# Playbook: Zero-Port Personal Agent Protocol (Poppy v1.0) Federation

**Category:** `Security / Protocols / Personal Agent / Inbound Isolation`  
**Original Concept:** `Andrew & Jon` • **Field Execution & Postmortem:** `Jon & Andrew`  
**Peer Overrides:** `variants/<peer>/` and `~/.gemini/mesh/`

---

## 1. Architectural Intent & Invariants

This playbook governs how sovereign personal agents federate with external corporate agents via the **Personal Agent Protocol ("Poppy" v1.0)** published by Sierra & Meta (November 14, 2026), while preserving 100% sovereign isolation, zero inbound open ports, and strict privacy against cross-vendor tracking.

- **Invariant 1 (Strict Client Metadata Decoupling & Neutral Identity):** Personal agents must never present an operator-attributable domain name as their `client_id`. Agents present shared neutral identities hosted in Ring 2/3 (`https://commons.three-ring-agents.org/agent.json`), shielding the operator's private home network and identity.
- **Invariant 2 (Zero Inbound Listening Ports):** External callbacks, push webhooks, and conversation streams must terminate at a serverless public edge (Cloudflare Worker) and transfer via pull-only queues (GCP Pub/Sub `listen_once.py`). No port forwarding, public IP exposure, or dynamic DNS endpoints on local firewalls.
- **Invariant 3 (MPA Plan-Bound Irreversible Action Gate):** Any operation with Poppy `scope_hints.changes: "irreversible"` or financial terms must never be auto-executed by an LLM turn. It must be sealed into a Plan Artifact and confirmed via an out-of-band `Poppy-Approval` token.
- **Invariant 4 (Ephemeral Delegated Keys & Pairwise Rotation):** To prevent cross-vendor tracking and fingerprinting (Issue #31), the personal agent generates pairwise unique pseudonymous `sub` IDs, rotates root key `kid`s, and signs per-request `Poppy-Session` JWTs using ephemeral in-memory EC P-256 keys vouched for by short-lived delegations (`poppy_dlg`, max 24h).
- **Runtime Config Keys (`~/.gemini/state/config.json`):**
  - `poppy.client_id`: `https://commons.three-ring-agents.org/agent.json`
  - `poppy.root_key_pointer`: `op://Agent-<User>/Poppy/root_key_pem`
  - `poppy.pubsub_topic`: `projects/{{PUBSUB_PROJECT_ID}}/topics/{{PUBSUB_TOPIC_ID}}`
  - `poppy.default_scope`: `orders:read`

---

## 2. Pitfalls & Field Postmortems ("What Broke / Ordering Gotchas")

- **Gotcha 1 (Issue #31 Cross-Vendor Correlation via Static Root `kid` in `poppy_dlg`):**
  - *Symptom:* Even when using pairwise pseudonymous `sub` identifiers, separate corporate vendors correlated user activity because the `poppy_dlg` token referenced the exact same root `kid` in `jwks.json`.
  - *Mitigation:* Generate pairwise unique root signing keys or rotate `kid` identifiers in `jwks.json` on a regular schedule.
- **Gotcha 2 (Session JWT Replay & NTP Clock Drift — `DE-TIME-01`):**
  - *Symptom:* Vendor gateways rejected `Poppy-Session` JWTs with `invalid_session` when host clock drifted by >60 seconds against NIST time.
  - *Mitigation:* Ensure `chrony`/NTP is synchronized on the host before issuing short-lived (60s acceptance window) Session JWTs.
- **Gotcha 3 (Web Bot Auth HTTPSig Requirement Drift):**
  - *Symptom:* Corporate bot management layers (Akamai, Cloudflare Bot Management) at certain vendors dropped Poppy requests before reaching the application layer when RFC 9421 / Web Bot Auth HTTP Message Signatures were omitted.
  - *Mitigation:* Include the recommended RFC 9421 operator signature covering `Poppy-Session` and `Authorization` headers using the edge worker.
- **Gotcha 4 (Direct Sign-In URL Parameter Poisoning on Mobile Forwarding):**
  - *Symptom:* Opening authorization URLs on secondary devices allowed forwarded links to approve scopes without user consent if `prompt=consent` was omitted.
  - *Mitigation:* Enforce `prompt=consent` on all authorization requests per Poppy v1.0 Section 4.2.

---

## 3. Pre-Flight & Post-Flight Verification Probes

Deterministic verification commands:

```bash
# Pre-Flight: Verify 100% stdlib Poppy client runs clean with zero pip imports
python3 ~/.gemini/commons/skills/poppy-client/scripts/poppy_client.py selftest

# Scope Inspection Probe: Verify scope_hints -> MPA tier mapping on live endpoint
python3 ~/.gemini/commons/skills/poppy-client/scripts/poppy_client.py inspect-scopes personalagentprotocol.org

# Post-Flight: Verify Outbound Redaction Gate on newly staged files
python3 ~/.gemini/commons/skills/sync-commons/scripts/redact_check.py scan
```

---

## 4. Seven-Point 3P Supply-Chain & DIY Evaluation Scorecard

**Target:** `personal-agent-protocol/personal-agent-protocol`  
**Evaluated Commit SHA:** `67647328c0d88d58cfa84b1d852d5b1852cf0eb9` (Date: 2026-11-16; v1.0 freeze: `8c02b4282eda53468a7c09412558bc8b060d95f6`)  
**License:** `Apache-2.0` (`LICENSE`, SHA `d645695673349e3947e8e5ae42332d0ac3164cd7`)  
**Maintainers:** Sierra & Meta (80+ listed industry design partners including 1Password, Cloudflare, OpenAI, Stripe, Visa, Salesforce, Plaid, Okta)

| Check | Verification Criterion | Status | Technical Audit Finding |
| :--- | :--- | :---: | :--- |
| **1. Obfuscation & Dynamic Execution** | No minified blobs, no `eval`/`exec`, no hidden Unicode homoglyphs. | **`PASS`** | Clean UTF-8 TypeScript & MDX. No dynamic runtime code generation. |
| **2. Transitive & Second-Stage Downloads** | No postinstall hooks, unpinned runners, or unreviewed npm packages. | **`PASS`** | Zero lifecycle hooks. `pnpm-workspace.yaml` enforces 4-day release aging. Validator in `kit/company/validate/` has **zero npm dependencies**. |
| **3. Privilege & Persistence Boundaries** | No root, sudo, SUID, launchd plists, or systemd daemons. | **`PASS`** | Runs unprivileged. Validator local state strictly confined to `.poppy/` with mode `0600`. |
| **4. Secret & Filesystem Boundaries** | No access to `~/.ssh`, `~/.gemini`, 1Password, Keychain, or `.env`. | **`PASS`** | Zero scanning or access of private system or cloud credential paths. |
| **5. Network Egress & Telemetry** | No unauthorized telemetry beacons, analytics, or reverse shells. | **`PASS / STRIPPED`** | Docs site bundles `@vercel/analytics: 2.0.1` for public web traffic; stripped from ingested schemas and client CLI. |
| **6. Static & CVE Analysis** | Clean vulnerability scans and JSON Schema Draft 2020-12 compliance. | **`PASS`** | All schemas validate cleanly; zero CVE disclosures against the specification. |
| **7. First-Party DIY vs. 3P Dependency** | `<200` LOC glue logic rule: prefer first-party stdlib implementation. | **`STRONG DIY`** | **100% First-Party DIY Approved.** Poppy is an open RFC-based HTTP/JSON/JWT protocol. Our first-party client (`poppy_client.py`) is 161 LOC in Python stdlib using `/usr/bin/openssl` for ES256 JWS signing, eliminating all external pip dependencies. |

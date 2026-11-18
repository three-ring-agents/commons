# Playbook: `Zero-Port Self-Hosted Poppy Identity & Edge Push Quarantine`

**Category:** `Security / Protocol / Edge Identity`  
**Original Concept:** `Andrew & Jon` • **Field Execution & Postmortem:** `Jon & Andrew`  
**Peer Overrides:** Optional `variants/andrew/` and `variants/jon/`

---

## 1. Architectural Intent & Invariants

Enable self-hosted personal agents (running on home hardware or local runtimes such as Antigravity and Stanford OpenJarvis) to participate in **Poppy — Personal Agent Protocol v1.0** without exposing inbound home ports, leaking Ring 1 personal domains, or trusting unverified merchant webhooks:

- **Invariant 1 (Zero-Correlation `client_id` / `jwks_uri`):** Host the agent's `client.json` and `jwks_uri` on a neutral edge origin (e.g., Cloudflare Worker) rather than a homeowner's personal Ring 1 domain. Rotate per-merchant `poppy_dlg` signing keys so `Poppy-Session` JWTs cannot be correlated across businesses.
- **Invariant 2 (Tokens & Keys Out of Model Context):** OAuth access tokens, refresh tokens, `Poppy-Session` JWTs, and ES256 private keys must remain strictly outside LLM context in Ring 1 secret storage (`op://Agent-{{OPERATOR}}/Poppy-Identity/...` or `~/.gemini/state/` `0600`).
- **Invariant 3 (Revision-Hash-Bound Tier 3 Approvals):** Map Poppy `scope_hints` fail-closed (`none` → Tier 1, `reversible` → Tier 2, `irreversible` or `operations` v3 `exact-terms` → Tier 3 MPA/hardware approval) and bind every Tier 3 approval token to the canonical SHA-256 `terms_revision_hash` of the presented terms.
- **Invariant 4 (Edge-Verified Push Quarantine):** Verify merchant Poppy JWS signatures at the Cloudflare Worker edge and route asynchronous merchant payloads into an isolated quarantine queue separate from trusted Ring 2 peer buses, parsed only by a Stage 1 taint-isolated reader.
- **Runtime Config Keys (`~/.gemini/state/config.json` & `~/.gemini/mesh/mesh.json`):**
  - `poppy.edge_client_id_url`: Neutral HTTPS `client_id` metadata URL.
  - `poppy.jwks_uri`: Public JWKS endpoint for rotated per-merchant `poppy_dlg` keys.
  - `poppy.quarantine_queue`: Isolated async merchant webhook queue (never the Ring 2 peer bus).
  - `poppy.private_key_pointer`: `op://Agent-{{OPERATOR}}/Poppy-Identity/es256_private_key`.

---

## 2. Pitfalls & Field Postmortems ("What Broke / Ordering Gotchas")

- **Gotcha 1 (Cross-Merchant Domain Correlation):** Using a personal domain as the Poppy `client_id` leaks the operator's household identity across every merchant visited, undermining Poppy's per-company pseudonymous `sub` privacy guarantee. Always use a neutral Worker origin + per-merchant rotated keys.
- **Gotcha 2 (TOCTOU Terms Bait-and-Switch):** Approving an `operations` v3 action by operation ID alone allows terms to drift if a merchant updates pricing or fees between quote and retry. Always compute `terms_revision_hash` over the canonical JSON terms and verify it matches before retrying idempotently.
- **Gotcha 3 (Shared Bus Taint):** Feeding asynchronous merchant webhook payloads onto the trusted Ring 2 peer federation bus creates an indirect prompt injection (IPI) lateral-movement path across peers. Keep merchant webhooks on a separate edge-verified quarantine queue.

---

## 3. Pre-Flight & Post-Flight Verification Probes

Deterministic commands the agent must run before and after applying changes:

```bash
# Pre-Flight Probe: Verify poppy_discover.py self-tests and Ring 3 OPSEC hygiene
python3 ~/.gemini/commons/skills/poppy-client/scripts/poppy_discover.py --self-test
python3 ~/.gemini/commons/skills/redact-gate/scripts/scrub.py --check ~/.gemini/commons/skills/poppy-client
python3 ~/.gemini/commons/skills/redact-gate/scripts/scrub.py --check ~/.gemini/commons/playbooks/zero-port-poppy-identity

# Post-Flight Probe: Verify neutral HTTPS client_id metadata and discovery reachability
python3 ~/.gemini/commons/skills/poppy-client/scripts/poppy_discover.py --origin https://example.com
```

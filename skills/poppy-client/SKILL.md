---
name: poppy-client
description: Portable, stdlib-first Poppy (Personal Agent Protocol v1.0) client skill for discovering merchant /.well-known/poppy.json capabilities, mapping scope_hints to Tier 1-3 MPA policies, binding Tier 3 operations v3 exact-terms to a deterministic revision hash, and isolating external tokens and async webhooks from Ring 1/Ring 2 state.
file_names:
    - scripts/poppy_discover.py
---
# Poppy v1.0 Client (`poppy-client`)

Enables any `SKILL.md`-compatible agent harness (Antigravity, OpenJarvis, Claude Code, Codex, OpenClaw) to interact safely with external businesses implementing **Poppy — Personal Agent Protocol v1.0** (`https://personalagentprotocol.org/`).

## Core Security & OPSEC Invariants

1. **Zero-Correlation `client_id` / `jwks_uri`:**
   - Never serve `client.json` or `jwks_uri` from a homeowner's personal Ring 1 domain.
   - Serve static `client_id` metadata from a neutral, zero-port edge origin (e.g., a Cloudflare Worker) and rotate per-merchant `poppy_dlg` signing keys so `Poppy-Session` JWTs cannot be correlated across merchants.
2. **Tokens & Signing Keys Strictly Out of Model Context:**
   - Never pass OAuth access tokens, refresh tokens, `Poppy-Session` JWTs, or ES256 private keys into LLM prompts or Ring 3 logs. Store secret pointers in Ring 1 (`op://Agent-{{OPERATOR}}/Poppy-Identity/...` or `~/.gemini/state/` `0600`).
3. **`scope_hints` → Tier 1–3 MPA Policy Mapping:**
   - `changes: "none"` → **Tier 1 (Autonomous Read)**
   - `changes: "reversible"` → **Tier 2 (Stage & Log)**
   - `changes: "irreversible"` or `operations` v3 `exact-terms` → **Tier 3 (Fail-Closed Hardware / MPA Approval)** bound to the exact SHA-256 `terms_revision_hash` of the returned terms payload.
4. **Edge-Verified Push Quarantine:**
   - Route asynchronous merchant webhooks through an edge-verified JWS quarantine queue **separate from trusted Ring 2 peer buses**, and process them with a Stage 1 taint-isolated reader.

## Quick Commands

```bash
# Discover a merchant's /.well-known/poppy.json and map scope_hints to Tier 1-3
python3 ~/.gemini/commons/skills/poppy-client/scripts/poppy_discover.py \
  --origin https://shop.example.com

# Compute deterministic revision hash for an operations v3 exact-terms JSON payload
python3 ~/.gemini/commons/skills/poppy-client/scripts/poppy_discover.py \
  --hash-terms /tmp/poppy_terms.json

# Run built-in stdlib self-tests
python3 ~/.gemini/commons/skills/poppy-client/scripts/poppy_discover.py --self-test
```

See also: `playbooks/zero-port-poppy-identity/PLAYBOOK.md` for the neutral Cloudflare Worker `client_id` / `jwks_uri` and edge-verified push quarantine architecture.

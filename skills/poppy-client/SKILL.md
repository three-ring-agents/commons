---
name: poppy-client
description: Personal Agent Protocol (Poppy v1.0) client for zero-port B2C vendor federation, ES256 session signing, scope-to-MPA inspection, and exact-terms operation approval. 100% Python standard library with zero third-party pip dependencies, using local openssl CLI for cryptographic signing. Compatible with Antigravity, Claude Code, OpenClaw, and Stanford OpenJarvis.
---

# Personal Agent Protocol Client (`poppy-client`)

The `poppy-client` skill provides a clean-room, 100% Python standard library implementation of the **Personal Agent Protocol ("Poppy" v1.0)** published by Sierra & Meta (November 14, 2026). It enables sovereign personal agents to federate with commercial enterprise agents (airlines, hotels, e-commerce, banking, support) without browser scraping, credential sharing, or third-party pip dependencies.

## 1. Architectural Overview & Wire Standards

Poppy v1.0 establishes a multi-layer federation model between a Personal Agent and a Company:

| Protocol Layer | Standard / RFC | Purpose in `poppy-client` |
| :--- | :--- | :--- |
| **Discovery** | `/.well-known/poppy.json` | Discovers company APIs (OpenAPI, MCP), agent endpoints, supported versions, and OAuth scopes. |
| **Agent Identity** | OAuth Client ID Metadata (CIMD) | Advertises public client metadata (`agent.json`) and public JWKS (`jwks.json`). |
| **Two-Tier JWS** | RFC 7515 / RFC 7519 / RFC 7800 | Root key signs delegation (`poppy_dlg`); ephemeral delegated key signs per-request `Poppy-Session` JWT. |
| **Access-on-Demand** | RFC 6749 / RFC 9449 (DPoP) / RFC 9728 | OAuth 2.0 authorization with `ath` binding and declarative `scope_hints`. |
| **Operations v3** | RFC 9651 Structured Headers | Exact-terms revision hash binding (`Poppy-Approval`) guaranteeing at-most-once mutation execution. |

## 2. CLI Tool Usage (`scripts/poppy_client.py`)

The skill CLI requires **Python 3.9+** and standard system `/usr/bin/openssl`. It has zero pip dependencies.

### Command Reference

```bash
# 1. Run local self-test (validates keygen, delegation, JWS signing, scope mapping, and approval headers)
python3 scripts/poppy_client.py selftest

# 2. Discover a company's Poppy v1.0 capabilities
python3 scripts/poppy_client.py discover example.com

# 3. Inspect company scopes and map scope_hints to Plan-Bound MPA Tiers (Tier 1/2/3)
python3 scripts/poppy_client.py inspect-scopes example.com

# 4. Generate a signed Poppy-Session JWT header payload
python3 scripts/poppy_client.py sign-session \
  example.com POST https://api.example.com/orders/cancel \
  https://commons.three-ring-agents.org/agent.json \
  ~/.gemini/state/keys/root_key.pem ~/.gemini/state/keys/del_key.pem

# 5. Execute an authenticated or signed-out Poppy API request
python3 scripts/poppy_client.py request \
  POST https://api.example.com/orders/cancel \
  https://commons.three-ring-agents.org/agent.json https://auth.example.com \
  ses_01JD8ZK3Q9 usr_pairwise_9821 \
  ~/.gemini/state/keys/root_key.pem ~/.gemini/state/keys/del_key.pem \
  '{"reason": "duplicate"}' "access_token_xyz" \
  '{"operation_id": "op_987", "revision": "rev_1", "approver": "user"}'
```

## 3. Scope Hints to Plan-Bound MPA Mapping

Poppy v1.0 declares `auth.scope_hints` with two dimensions:
- `changes`: `"none"` | `"reversible"` | `"irreversible"`
- `personal_data`: `true` | `false`

`poppy-client` deterministically classifies these hints into our 3-tier Plan-Bound Access-on-Demand (AoD) model:

- **Tier 1 (Readonly / Safe):** `changes: "none"`. Auto-allowed for autonomous execution without interactive prompts.
- **Tier 2 (Mutate / Reversible):** `changes: "reversible"`. Auto-staged with structured audit logging.
- **Tier 3 (Destroy / High-Impact):** `changes: "irreversible"`. Hard-denied in automated execution streams. Requires an explicit Plan Artifact sealed into an `mpa-plan` and confirmed via user instruction before dispatching a `Poppy-Approval` token.

## 4. Ephemeral Key Delegation & Anti-Tracking Architecture

To mitigate cross-vendor tracking and fingerprinting (Issue #31):
1. **Neutral Client Identity:** The personal agent identifies itself via a neutral shared URI (`https://commons.three-ring-agents.org/agent.json`), never an individual operator's personal domain.
2. **Ephemeral Delegations:** The root key in `jwks.json` signs a short-lived delegation token (`poppy_dlg`, max 24h) containing an in-memory EC P-256 public key.
3. **Pairwise Separation:** Every target vendor receives unique pseudonymous `sub` identifiers, unique ephemeral `kid` thumbprints, and unique delegation `jti` nonces.

# Playbook: Multi-Model Aggregate Utility Routing & `$100/mo` GCP Credit Waterline Controller

**Category:** `Compute Topology / Cost Optimization / Multi-Agent Routing`  
**Commons Namespace:** `three-ring-agents/commons/playbooks/multi-model-credit-waterline`  
**Peer Overrides:** Optional `profiles/<archetype>/ or ~/.gemini/mesh/profiles/<archetype>/`

---

## 1. Our Setup

### Architectural Intent & Invariants

Optimizes multi-agent execution across **two separate 5-hour rolling Antigravity quota pools** (Pool 1: Google Gemini native models; Pool 2: Partner Claude & OpenAI models) and the **bundled `$100/mo` Google Developer Program Cloud/GenAI credit grants** included with Google AI Ultra (`$199.99/mo`, where each monthly `$100` grant remains valid for 12 months and rolls over via FIFO accounting).

Our setup enforces four deterministic invariants via `MODEL_CATALOG.json`, `BURST_QUEUE_WATERLINE.json`, and the `0600` SQLite WAL ledger (`multi_model_spend_ledger.db`):

- **Invariant 1 (Aggregate Utility Function — `Performance × Quota Burn × Cost × Zero-Training Privacy`):**
  - **Pool 1 (Google Gemini Native Pool):** Route high-volume repo/log scanning, mechanical checks, and batched JSON extraction to `gemini-3.8-flash` (`1x` burn weight); interactive multi-step MCP coordination to `gemini-4-argon-medium` (`~3x` burn weight); and reserve `gemini-4-carbon-high` (`~10x` burn weight) strictly for deep algorithmic or security protocol synthesis.
  - **Pool 2 (Partner Claude & OpenAI Shared Pool):** Route complex Go/Python refactoring and concurrency state-machine work to `claude-sonnet-5-5` (`~4x` burn weight); independent cross-family adversarial verification (`@verifier`) to `gpt-oss-120b-medium` (`~3.5x` burn weight); and reserve `claude-opus-5-5` (`~12x` burn weight) for apex architectural decisions.
  - **Zero-Training Privacy Perimeter:** All native subagents/swarm workers and commercial API keys operate under commercial zero-training terms, allowing full repository context (`fork="coordinator"`, `workspace="inherit"`) without lossy AST scrubbing while maintaining strict 1Password `op://Agent-<User>/...` credential isolation.
- **Invariant 2 (Two-Lane Execution & FIFO Credit Tranche Ledger):**
  - **Lane A (`$0` API Spend):** Interactive sessions and native subagent swarms run on included Pool 1 / Pool 2 rolling quota.
  - **Lane B (Metered Batch API via `$100/mo` GCP Credits):** Bulk historical backfills and multimodal digests execute against accumulated `$100` monthly credit tranches (`credit_tranches` table on `<BILLING_ACCOUNT_ID>`), deducting spend in strict **First-In, First-Out (FIFO)** order by expiration date (`expires_at_utc`).
- **Invariant 3 (Strict Separation of One-Time Build/Backfill Cost vs. Ongoing Monthly OpEx):** Every workload in `BURST_QUEUE_WATERLINE.json` declares both its **One-Time Engineering/Backfill Cost (`$ USD`)** and its **Steady-State Monthly Operational Cost (`$/month`)**. Local deterministic Go/Python/SQLite daemons run at **`$0.00/mo`** steady-state token spend after initial build.
- **Invariant 4 (Pre-Flight Per-Domain Sub-Caps & Promotional Pricing Cliff Guards):** Before every batch API call, `check_pre_flight_guardrail()` verifies per-run and per-domain monthly sub-caps across isolated GCP projects (`<GCP_PROJECT_ID>`) and tracks promotional intro pricing windows so batch backfills complete before scheduled rate step-ups.

#### Runtime Config Keys (`~/.gemini/state/config.json`)

```json
{
  "multi_model_waterline": {
    "model_catalog_path": "~/.gemini/state/MODEL_CATALOG.json",
    "waterline_queue_path": "~/.gemini/state/BURST_QUEUE_WATERLINE.json",
    "spend_ledger_db": "~/.gemini/state/multi_model_spend_ledger.db",
    "billing_account_placeholder": "<BILLING_ACCOUNT_ID>",
    "gcp_project_placeholder": "<GCP_PROJECT_ID>",
    "default_waterline_usd": 100.0
  },
  "secrets": {
    "gemini_burst_api_key": "op://Agent-<User>/AI-Burst-Keys/gemini_api_key"
  }
}
```

### Pitfalls & Field Postmortems ("What Broke / Ordering Gotchas")

- **Gotcha 1 (Burning Carbon 4 `10x` or Opus 5.5 `12x` on Cold Repo Discovery):** Spawning flagship reasoning models to grep directories or poll status endpoints exhausts a 5-hour rolling quota pool in minutes. Always gather context with `Flash 3.8` (`1x`) or `Argon 4` (`~3x`) first, then pass `fork="coordinator"` when delegating surgical synthesis to `Sonnet 5.5`.
- **Gotcha 2 (Conflating One-Time Historical Backfill Spend with Recurring Monthly OpEx):** A `$10–$30` one-time multi-year corpus backfill looks expensive if mistaken for a daily recurring job, whereas incremental daily delta syncs on `Flash 3.8` cost `< $1.50/mo` (and local deterministic SQLite FTS5 queries cost `$0.00/mo`). Always separate `one_time_cost_usd` and `steady_state_monthly_usd` in `BURST_QUEUE_WATERLINE.json`.
- **Gotcha 3 (Unclaimed or Expired `$100/mo` Google Developer Program Credits):** Google AI Ultra (`$199.99/mo`) bundles `$100/mo` in Cloud/GenAI credits (`https://developers.google.com/program/my-benefits`) that accumulate up to `$1,200/yr` with a 12-month expiry per tranche. Tracking each grant in a FIFO SQLite ledger ensures oldest tranches are consumed first before expiration.
- **Gotcha 4 (Double-Spending on Interrupted Batch Backfills):** Without an idempotent `processed_items` checkpoint table in SQLite (`0600` WAL), restarting a batch job re-processes already extracted records. Always commit per-batch cursors alongside `record_spend_and_deduct_fifo()` using exact `usageMetadata` token counts.

### Pre-Flight & Post-Flight Verification Probes

```bash
# Pre-Flight Probe 1: Run generic Credit Waterline Controller simulation at $100 threshold
python3 ~/.gemini/commons/playbooks/multi-model-credit-waterline/scripts/waterline_planner.py --waterline-usd 100

# Pre-Flight Probe 2: Verify 3-Stage Outbound Redaction Gate on playbook files
python3 ~/.gemini/commons/skills/redact-gate/scripts/scrub.py --check ~/.gemini/commons/playbooks/multi-model-credit-waterline

# Post-Flight Probe 1: Verify Stage 1 Redaction Gate cleanliness across Commons
python3 ~/.gemini/commons/skills/sync-commons/scripts/redact_check.py scan
```

---

## 2. Other Options

When configuring multi-model routing and budget governance for a household or engineering workspace (`profiles/<archetype>/`), consider these alternatives:

1. **Single-Provider Homogeneous Routing (All Tasks on One Default Model):**
   - *Pros:* Zero routing configuration or catalog maintenance required.
   - *Cons:* Either under-powers complex concurrency/security reviews (if pinned to a lightweight model) or rapidly exhausts the 5-hour rolling quota pool on trivial file scans (if pinned to a heavyweight model).
2. **Gemini Batch API (50% Async Discount, 24h Turnaround) vs. Synchronous Batched JSON Calls:**
   - *Pros:* Google's asynchronous Batch API offers a 50% token discount for non-urgent jobs that can wait up to 24 hours.
   - *Cons:* Interactive or same-hour backfills benefit from synchronous multi-item batching (packing 10–20 records into a single structured `responseSchema` call on `gemini-3.8-flash`), which achieves similar cost reduction with immediate completion and deterministic SQLite checkpointing.
3. **Hard Cloud Billing Budget Shutoffs vs. Local Pre-Flight SQLite FIFO Ledger:**
   - *Pros:* GCP Cloud Billing budgets and Pub/Sub alerts provide an authoritative cloud-side backstop.
   - *Cons:* Cloud Billing export to BigQuery lags by several hours; a local synchronous SQLite WAL ledger (`multi_model_spend_ledger.db`) enforces sub-second pre-flight caps (`max_run_usd`) on every batch request before tokens are spent.
4. **Local Open-Weights Models (Ollama / vLLM on Homelab GPU or Apple Silicon):**
   - *Pros:* Zero cloud API spend and 100% air-gapped local execution on `<LAN_SUBNET>`.
   - *Cons:* Consumes local Unified Memory / power on the home server and trails frontier models on complex multi-file code synthesis or nuanced multimodal PDF extraction, whereas bundled `$100/mo` GCP credits already provide `$1,200/yr` of frontier cloud batch compute at zero incremental out-of-pocket cost.

---

## 3. Suggested Reading

- **Model Routing, Quota & Credit Documentation:**
  - Google Developer Program Benefits (`https://developers.google.com/program/my-benefits`) — Monthly Cloud & GenAI credit grant terms and 12-month rollover mechanics.
  - Gemini API Structured Outputs (`responseSchema`) & Token Metering (`usageMetadata`: `promptTokenCount`, `candidatesTokenCount`, `thoughtsTokenCount`).
- **Related Commons Playbooks & Skills:**
  - `playbooks/multi-model-credit-waterline/PLAYBOOK.md` — Companion reference script (`scripts/waterline_planner.py`).
  - `playbooks/zero-clutter-daemon-iac/PLAYBOOK.md` — Daily/weekly automated catalog evolution (`memory.daily_evolver`) via zero-clutter OS daemons.
  - `playbooks/plan-bound-mpa-and-secret-isolation/PLAYBOOK.md` — Segmented 1Password `op://Agent-<User>/...` secret hydration for burst API keys.

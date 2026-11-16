# Playbook & Blueprint: Supervised Family Intent Gatekeeper (`<18` Access)

**Category:** Household AI Safety & Bounded Agent Routing  
**Authors:** Jon Chu & Andrew Mitry (`dont-tell-the-wifi` Shared Commons)  
**Companion Code:** `gatekeeper_blueprint.py`

---

## 1. Architectural Intent & Invariants

When sharing a household AI assistant + Google Antigravity setup across adults (`18+` Google AI Ultra plan members) and supervised minors (`<18` Family Link accounts), the system must enforce four non-negotiable security invariants:

1. **Fail-Closed Identity Resolution:**
   - Every incoming request (iMessage, voice webhook, Google Chat, or CLI) must resolve the sender handle against an explicit household roster stored in private `~/.gemini/state/family_hub_config.json`.
   - Unknown or spoofed handles default to `BLOCKED_UNKNOWN` before any LLM or tool invocation occurs (never defaulting to the plan manager's identity).
2. **Prompt-Injection Proof Schema Boundary (`MinorIntentEnum` + Regex):**
   - Supervised `<18` users never receive direct shell, code execution, smart-home lock/vehicle control, financial tool, or arbitrary web browsing access.
   - All control tags are stripped pre-classification, and minor requests are constrained to a closed `response_schema` enum (`GENERATE_STUDY_WORKSHEET`, `CHECK_SCHOOL_SCHEDULE`, `CHECK_SPORTS_READINESS`, `ADD_SHOPPING_ITEM`, `REQUEST_CALENDAR_EVENT`, `REFUSE_OUT_OF_SCOPE`) with `BLOCK_LOW_AND_ABOVE` safety settings.
   - A second-layer deterministic validator (`validate_schema_payload`) verifies every field against strict alphanumeric regexes (`^[A-Za-z0-9 _,.\-()'&:]{2,80}$`) so second-order prompt injection cannot reach downstream tools.
3. **Least-Privilege Scoped Workspace Output:**
   - Generated study worksheets or quizzes are written strictly to the minor's scoped Google Drive folder (configured in private `family_hub_config.json`) via a least-privilege worker or scoped Drive parent ID.
4. **Comms Hold Gate (`HOLD_FAMILY_COMMS=1` Default during Rollout):**
   - Outbound notifications, Drive share emails, and chat/iMessage dispatches to family members remain staged in an audit log until the plan manager explicitly flips `HOLD_FAMILY_COMMS=0`.

---

## 2. Pitfalls & Field Postmortems ("What Broke / Ordering Gotchas")

- **Pitfall 1 — Second-Order Tag Injection in Upstream Chat Bots:**
  - *What happens:* If the household assistant parses XML/bracket action tags (e.g., `<SMART_HOME>`, `<SEND_EMAIL_DRAFT>`) from LLM output, a clever teen prompt can trick an unconstrained LLM into echoing an action tag.
  - *Fix:* Strip all XML action tags on *input* (`sanitize_input_text`) AND route `<18` turns through the structured `GATEKEEPER_RESPONSE_SCHEMA` classifier before the general conversational prompt ever runs.
- **Pitfall 2 — Hardcoding Family Roster PII in Shared Code:**
  - *What happens:* Storing student names, school names, teacher names, phone numbers, or scoped Drive Folder IDs inside the Python module prevents sharing improvements across households.
  - *Fix:* Keep all household roster entries, course catalogs, and Drive folder IDs in `~/.gemini/state/family_hub_config.json` (Tier 1 private state) and keep `gatekeeper_blueprint.py` in `~/.gemini/commons` 100% generic.

---

## 3. Pre-Flight & Post-Flight Verification Probes

Run these deterministic probes before and after deploying or updating the gatekeeper:

```bash
# Probe 1: Verify zero private household PII in the shared blueprint
python3 ~/.gemini/commons/skills/sync-commons/scripts/redact_check.py scan

# Probe 2: Run the built-in self-test suite (verifies fail-closed unknown sender,
# shell/smart-home injection refusal, and valid study worksheet routing)
python3 ~/.gemini/commons/templates/supervised-intent-gatekeeper/gatekeeper_blueprint.py --self-test
```

# Playbook: Sovereign Personal Agent / Chief of Staff Architecture

**Category:** `Security / Personal Agent / Cross-Household Federation`  
**Original Concept:** `Andrew` • **Field Execution & Postmortem:** `Andrew & Jon`  
**Peer Overrides:** Optional `profiles/<archetype>/` and `~/.gemini/mesh/variants/<operator>/`

---

## 1. Architectural Intent & Invariants

Provides a Tier-0 Sovereign Personal Agent architecture in Antigravity Remote Conversations and Google Chat (`#humans` / `#agent-backchannel`), distinct from any Supervised Family AI Assistant, combining **Noah Shinn's _Reflexion_ & _τ-bench_** reliability harness, **Meta Muse's Out-of-Model Sentinel & Watch-and-Approve Spend Cards**, and **Instinct's Compartmentalized Concierge & Double-Blind Trusted Person Network**.

- **Invariant 1 (Out-of-Model Action Gate):** Every agent action is classified outside the LLM into `TIER_A_READ` (`ALLOW`), `TIER_B_STAGE` (`STAGE_AND_LOG`), or `TIER_C_COMMIT` (`REQUIRE_CONFIRMATION` via cryptographic `KIT-APR-*` / `mpad` tokens).
- **Invariant 2 (Inbound IPI Quarantine):** External text (vendor quotes, web pages, Doc comments, peer envelopes) is tagged `PROVENANCE=EXTERNAL_UNTRUSTED`. Stripped of `<KIT_*>` XML action tags and hard-locked against triggering Tier C actions on the same turn.
- **Invariant 3 (One-Way Family Boundary):** When delegating household schedule queries to a Family Gatekeeper, `ALVIN_HOLD_FAMILY_COMMS=1` is enforced by default so personal agent runs never trigger accidental outbound family messages.
- **Invariant 4 (Double-Blind Peer Federation):** Cross-household scheduling (`freebusy-intersect`) exports only quantized `BUSY` boolean intervals (`TIER_3_DOUBLE_BLIND`), stripping all event titles, locations, and family details prior to intersection.
- **Runtime Config Keys (`~/.gemini/state/config.json`):**
  - `gchat_rooms.humans.space_id`: `spaces/{{GCHAT_HUMANS_SPACE_ID}}`
  - `gchat_rooms.backchannel.space_id`: `spaces/{{GCHAT_BACKCHANNEL_SPACE_ID}}`
  - `concierge_identity.alias_email`: `op://Agent-<User>/Kitt-Concierge/alias_email`
  - `concierge_identity.virtual_card_token`: `op://Agent-<User>/Kitt-Concierge/virtual_card_token`
  - `pubsub.project_id`: `{{PUBSUB_PROJECT_ID}}` (Zero-Key Direct Google Account OAuth 2.0 via `pubsub` scope)

---

## 2. Pitfalls & Field Postmortems ("What Broke / Ordering Gotchas")

- **Gotcha 1 (Cloud VM FUSE `chmod` / `utime` Rejection):** On Antigravity Cloud Remote VMs, `/shared/user/.gemini` (`~/.gemini`) is a FUSE mount that rejects `chmod` and `utime` (`Operation not permitted`). Always stage Git operations in `/home/antigravity/antigravity-state` or `/home/antigravity/antigravity-commons` and copy byte streams back via `cat`.
- **Gotcha 2 (`gdocs` Granular Safe Mode vs. Full-Doc Import):** Running `gdocs mutate import-md --update` wipes native Kix comment anchors (`kix.*`) and Smart Chips. Always inspect `gdocs readonly list-comments {{GOOGLE_DOC_ID}} --json` first and use `gdocs mutate update-table` or `gdocs mutate batch` (`gdocs_comment.py`).
- **Gotcha 3 (Unencrypted Vault Staging in Drive PARA):** Never sync an unencrypted `_Vault_Staging` directory into `02_Areas` (`{{GOOGLE_DRIVE_FOLDER_ID}}`); keep raw financial or tax PDFs strictly inside `_Vault_Encrypted` or local Tier-0 storage.
- **Gotcha 4 (Google Family Group Calendar Hard-Lock — `DE-CAL-01`):** Google hard-locks the auto-generated `{{FAMILY_GROUP_CALENDAR_ID}}` (`group.calendar.google.com`) calendar to the human Google Family Group members and rejects ACL sharing with bot or service accounts (`403 cannotShareGroupCalendar`). Household stewards (`Kitt` / `Seville`) must use a standard secondary Google Calendar named `"Family"` shared via explicit ACLs.
- **Gotcha 5 (Google Chat Bot-to-Bot Wakeup Suppression — `DE-GCHAT-01`):** Google Chat suppresses bot-authored messages from triggering webhook or workspace events for other Chat bots. Whenever an agent posts to `#agent-backchannel` (`spaces/{{GCHAT_BACKCHANNEL_SPACE_ID}}`), always pair the Chat message with an out-of-band wakeup envelope on GCP Pub/Sub (`projects/{{PUBSUB_PROJECT_ID}}/topics/{{PUBSUB_TOPIC_ID}}`).
- **Gotcha 6 (1:1 DM & Onboarding Email Watcher Gap):** Polling only shared group spaces (`#humans` and `#agent-backchannel`) misses 1:1 direct messages and direct onboarding emails when a peer brings a new agent identity online. Include known peer 1:1 DM spaces and peer sender email addresses (`from:<peer_email>`) in the consolidation watcher loop.

---

## 3. Pre-Flight & Post-Flight Verification Probes

Deterministic commands the receiving agent must run before and after applying changes:

```bash
# Pre-Flight Probe: Verify 3-Stage Outbound Redaction Gate on ~/.gemini/commons
python3 ~/.gemini/commons/skills/sync-commons/scripts/redact_check.py scan

# Post-Flight Probe: Run the 25-test tau-bench policy & federation compliance suite
python3 ~/.gemini/state/skills/kit/scripts/test_kit_tau_bench.py -v
```

---
name: collab-roe
description: Shared Rules of Engagement (RoE) for cross-household agent-to-agent and human-to-agent collaboration across Google Docs, GitHub Commons, and shared chat spaces (~/.gemini/commons / dont-tell-the-wifi). Standardizes native Kix-anchored Google Docs comments (gdocs_comment.py InsertCommentRequest shim), inline shaded callout blocks, 3-section infrastructure playbooks (Intent, Pitfalls, Verification Probes), 1Password op:// config pointers, and non-blocking variants/<peer>/ overrides.
---
# Collaboration Rules of Engagement (`collab-roe`)

This skill defines the standard etiquette, formatting, and technical workarounds for agent-to-agent collaboration between **Andrew Mitry** and **Jon Chu** across `~/.gemini/commons` (`dont-tell-the-wifi`), shared Google Docs, GitHub, and Google Chat spaces.

## 1. Explicit Agent Attribution & High-Signal Style (Mandatory)

Both operators use Antigravity agents to review, draft, and exchange technical artifacts. Humans and peer agents must be able to immediately distinguish agent-authored text from direct human input:

* **Prefix every agent-authored review block, comment, PR description, or chat message** with:
  ```text
  [AGENT COMMENT — <Operator>'s Agent on behalf of <Operator>]
  ```
* **When logging automated syncs or actions**, use:
  ```text
  [AGENT ACTION — <Operator>'s Agent]
  ```
* **No conversational filler:** Omit greetings, pleasantries, and verbose transitions.
* **Use structured semantic tags:**
  * `Status: +1 / Adopted` — Explicitly confirms alignment so the peer agent knows no further debate is needed.
  * `Counter-Proposal:` — Proposes an alternative design with concise trade-offs.
  * `Extension Proposal:` — Adds a capability or edge-case guardrail to an accepted design.
  * `Lesson Learned / Quirk:` — Documents an empirical gotcha or production mistake.
  * `Question for <Peer>:` — Flags an open decision requiring human or peer-agent input.

## 2. Google Docs Review Standard (`gdocs_comment.py` Native Kix Shim + Inline Callouts)

> [!IMPORTANT]
> **Root Cause & Fix for `comments anchored to a text range are not available` in `gdocs` (`CLI_VERSION=986250228`):**
> 1. **Google Docs API v1 (`how-tos/suggestions`):** Google Docs API v1 supports native Kix-anchored comments via `documents.batchUpdate` (`InsertCommentRequest` / `insertComment`, `AddCommentReplyRequest`, `DeleteCommentRequest`).
> 2. **Why unpatched `gdocs-986250228` failed:** The stock `gdocs-986250228` binary (`google3/learning/gemini/agents/clis/gdocs/comments.go`) was compiled against an older `google3/third_party/golang/google_api/docs/v1/docs` struct that predates `InsertCommentRequest` and hits `errAnchoredCommentsUnavailable` (`"comments anchored to a text range are not available"`). Meanwhile, Drive API v3 `comments.create` cannot write a Kix `commentAnchor` (`kix.*`), causing `"Original content deleted"` in the Docs UI.
> 3. **Installed Fix (`scripts/gdocs_comment.py` + `gdocs` Binary Shim):**
>    * `scripts/gdocs_comment.py` calls `POST https://docs.googleapis.com/v1/documents/{docId}:batchUpdate` directly with `insertComment` (`InsertCommentRequest`), resolving exact UTF-16 `startIndex`/`endIndex` across tabs, paragraphs, and nested tables.
>    * `plugin_data/gdocs/bin/gdocs-986250228` wraps `gdocs-986250228.real` and transparently routes `gdocs mutate add-comment` to `scripts/gdocs_comment.py`, working identically on Cloud Remote Agent VMs (`jetski`, `/tmp/agy-plugin-tokens-*`) and local macOS/Linux hosts (`mac-mini`).

### Option A — Native Kix-Anchored Margin Comments (`gdocs mutate add-comment` / `gdocs_comment.py`)
Use for targeted inline review comments anchored to a specific phrase:

```bash
# 1. Via the transparent gdocs shim (or `gdocs_comment.py add-comment`):
gdocs mutate add-comment DOC_ID "[AGENT COMMENT — Jon's Agent on behalf of Jon] +1 / Adopted..." \
  --quote "Exact quoted text in doc" \
  --tab t.0

# 2. Or via flag-based `post` syntax (automatically prepends [AGENT COMMENT] header):
python3 ~/.gemini/commons/skills/collab-roe/scripts/gdocs_comment.py post \
  --doc-id "<DOC_ID>" \
  --operator "Andrew" \
  --quote "Exact quoted text in doc" \
  --content "Concise review note."

# 3. Reply to or delete a native comment:
python3 ~/.gemini/commons/skills/collab-roe/scripts/gdocs_comment.py reply DOC_ID doco.xxx "[AGENT COMMENT — ...] Reply text"
python3 ~/.gemini/commons/skills/collab-roe/scripts/gdocs_comment.py delete DOC_ID doco.xxx
```

### Option B — Inline Shaded Agent Callout Blocks (`make-batch` + `gdocs mutate batch`)
Use when placing structured milestone updates or review blocks directly in the document body (preserving all existing margin comments and Smart Chips):

```bash
# Generate a Granular Safe Mode batch JSON snippet:
python3 ~/.gemini/commons/skills/collab-roe/scripts/gdocs_comment.py make-batch \
  --operator "Andrew" \
  --bullets "Status: +1 / Adopted on dont-tell-the-wifi codename." "Provisioned shared folder and sync-commons." \
  --out /tmp/agent_comment_batch.json

# Insert after a heading (--after) or at a specific UTF-16 index (--index, bottom-to-top):
gdocs mutate batch DOC_ID --tab t.0 --after "Heading Text" -f /tmp/agent_comment_batch.json
```

## 3. Three-Section Infrastructure Playbook Standard

Whenever packaging an infrastructure playbook (e.g., UniFi Security Hardening, Supervised Family Intent Gatekeeper, Proxmox/VLAN configs) into `~/.gemini/commons/playbooks/` or `templates/`, include three declarative sections alongside upload-as-is code:

1. **Architectural Intent & Invariants (`INTENT.md`):** What security and operational properties must hold true regardless of hardware or firmware differences.
2. **Pitfalls & Field Postmortems (`POSTMORTEM.md` — "What Broke / Ordering Gotchas"):** Real-world mistakes, rule-ordering traps, or API quirks discovered in production so the peer agent doesn't repeat them.
3. **Pre-Flight & Post-Flight Verification Probes (`scripts/`):** Deterministic commands or scripts the receiving agent must run before and after applying changes to prove the invariants hold.

## 4. Dynamic `config.json`, `op://` Pointers, `variants/<peer>/`, & Redaction Gate

* **Never hardcode personal IDs:** Read operator-specific Drive IDs, repo names, and hostnames from `~/.gemini/state/config.json`.
* **1Password Secret Pointers (`op://`):** Store sensitive credentials in `config.json` as `op://Agent-<User>/<Item>/<Field>` URIs and resolve them at runtime via `op read` (or `redact_check.py resolve-config --resolve-op`).
* **Agree-to-Disagree by Default (`variants/<operator>/`):** Default to direct push to `main` after passing the 3-Stage Redaction Gate (`redact_check.py scan` and `redact-gate/scripts/scrub.py --check`). If hardware, versions, or opinions diverge, place operator-specific overrides in `variants/andrew/` or `variants/jon/` inside the skill or playbook directory.
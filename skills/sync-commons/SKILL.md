---
name: sync-commons
description: Synchronize the shared Antigravity Commons repository (~/.gemini/commons / dont-tell-the-wifi) between Andrew Mitry and Jon Chu across GitHub and Google Drive (dont-tell-the-wifi.bundle), enforcing the 3-Stage Pre-Push Redaction Gate (deterministic regex + ~/.gemini/state/redaction_rules.yaml + ratchet), 1Password op:// secret resolution, and automatic local/cloud skill registration.
---
# Shared Commons Sync & Redaction Gate (`sync-commons`)

Synchronizes `~/.gemini/commons` (**Codename: `dont-tell-the-wifi`**) across **Andrew Mitry** and **Jon Chu's** Antigravity platforms using a dual GitHub + Google Drive backend and a mandatory 3-Stage Pre-Push Redaction Gate.

## Canonical Backends

- **Local & Cloud Persistent Path:** `~/.gemini/commons` (`/shared/user/.gemini/commons` on Cloud VMs)
- **GitHub Repository:** `three-ring-agents/commons` (configured dynamically via `~/.gemini/state/config.json`)
- **Shared Google Drive Folder:** [dont-tell-the-wifi (Antigravity Commons)](https://drive.google.com/drive/folders/{{GOOGLE_DRIVE_FOLDER_ID}}) (`{{GOOGLE_DRIVE_FOLDER_ID}}`)
- **Proposal & Architecture Doc:** [Antigravity Cross-Platform Collaboration Proposal (Andrew & Jon)](https://docs.google.com/document/d/{{GOOGLE_DOC_ID}}/edit)

## Quick Commands

```bash
# 1. Check status of ~/.gemini/commons and run the Stage 1 Redaction Gate
~/.gemini/commons/skills/sync-commons/scripts/sync_commons.sh status

# 2. Run the 3-Stage Redaction Gate explicitly on ~/.gemini/commons
python3 ~/.gemini/commons/skills/sync-commons/scripts/redact_check.py scan

# 3. Ratchet an approved token into ~/.gemini/state/redaction_rules.yaml (Stage 3)
python3 ~/.gemini/commons/skills/sync-commons/scripts/redact_check.py allow "<token>"

# 4. Pull latest shared skills, templates, and playbooks from GitHub or Drive bundle
~/.gemini/commons/skills/sync-commons/scripts/sync_commons.sh pull

# 5. Run Redaction Gate, commit, push to GitHub (direct to main), and update Drive bundle
~/.gemini/commons/skills/sync-commons/scripts/sync_commons.sh push "Publish new skill or playbook"

# 6. Resolve config.json (including op://Agent-<User>/... 1Password secret pointers)
python3 ~/.gemini/commons/skills/sync-commons/scripts/redact_check.py resolve-config
```

## 3-Stage Pre-Push Redaction Gate Workflow

Every `sync_commons.sh push` automatically runs `redact_check.py scan` before creating a Git commit or updating the Drive bundle:

1. **Stage 1 (Deterministic Scrubber):** Scans all files in `~/.gemini/commons` against:
   - Private blocklist terms in `~/.gemini/state/redaction_rules.yaml` (household names, emails, phone numbers, internal hostnames, private Drive IDs).
   - Regex detectors for RFC1918 private subnets (`192.168.x.x`, `10.x.x.x`, `172.16-31.x.x`), MAC addresses, `/Users/<username>` paths, un-templated `op://` URIs, and unapproved Drive/Doc IDs.
2. **Stage 2 (Adversarial LLM Diff Check):** Before pushing narrative playbooks or postmortems, review the staged `git diff` output to verify no subtle topology or family PII remains.
3. **Stage 3 (Zero-Toil Auto-Publish + Ratchet):**
   - If 0 findings are flagged, `sync_commons.sh push` publishes automatically to `main` and updates `dont-tell-the-wifi.bundle` in the shared Google Drive folder.
   - If an ambiguous token is flagged and confirmed safe by the human operator, run `redact_check.py allow "<token>"` once to ratchet it into `~/.gemini/state/redaction_rules.yaml`.

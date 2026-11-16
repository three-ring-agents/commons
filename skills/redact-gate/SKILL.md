---
name: redact-gate
description: Three-Stage Outbound Redaction Gate for ~/.gemini/commons. Use before publishing, committing, or sharing any skill, playbook, postmortem, or diff to the shared Commons repository or Google Drive folder. Runs Stage 1 deterministic regex + personal blocklist scrubbing (~/.gemini/state/redaction_rules.yaml & 1Password), Stage 2 ambiguity flagging for adversarial LLM review, and Stage 3 self-learning token ratcheting.
---

# Outbound Redaction Gate (`redact-gate`)

Every artifact, skill, or field postmortem staged for `~/.gemini/commons` must pass this 3-stage "Human-on-the-Loop" sanitization pipeline before leaving the operator's household environment.

## Architecture: Three-Stage "Human-on-the-Loop" Pipeline

1. **Stage 1 — Deterministic Regex + Personal Blocklist Scrubber (`scripts/scrub.py`):**
   * Strips generic infrastructure & personal identifiers:
     * RFC1918 IPv4 addresses & CIDR blocks (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16` $\rightarrow$ `{{RFC1918_CIDR}}` / `{{RFC1918_IP}}`)
     * MAC addresses (`XX:XX:XX:XX:XX:XX` $\rightarrow$ `{{MAC_ADDRESS}}`)
     * Local mDNS / LAN hostnames (`*.local`, `*.lan`, `*.internal`, `*.home.arpa` $\rightarrow$ `{{INTERNAL_HOSTNAME}}`)
     * Local macOS/Linux user home paths (`/Users/<user>` $\rightarrow$ `/Users/{{USER}}`)
     * Raw Google Doc / Sheet / Slide / Drive Folder IDs in URLs ($\rightarrow$ `{{GOOGLE_DOC_ID}}`, `{{GOOGLE_DRIVE_FOLDER_ID}}`)
   * Applies the operator's private blocklist in `~/.gemini/state/redaction_rules.yaml` (backed by 1Password at `op://Agent-<Operator>/Redaction-Rules/rules.yaml`) covering family/minor names, school names, Wi-Fi SSIDs, and custom hostnames.

2. **Stage 2 — Heuristic & Adversarial LLM Review:**
   * `scripts/scrub.py --check <path>` outputs a JSON report of all Stage 1 replacements plus any **Stage 2 Ambiguity Candidates** (unfamiliar capitalized proper nouns near family/location keywords, hardcoded VLAN integers, or unparameterized `op://` vault names).
   * The agent inspects the scrubbed text and Stage 2 flags for subtle topology or minor-PII leakage.

3. **Stage 3 — Zero-Toil Auto-Publish + Self-Learning Ratchet:**
   * **Clean Pass (`0 Ambiguities`):** Proceeds automatically with zero human clicks.
   * **Flagged Token (`Needs Review`):** Prompt the operator once. If the operator confirms a token is sensitive, run:
     ```bash
     python3 ~/.gemini/commons/skills/redact-gate/scripts/scrub.py \
       --ratchet "SensitiveToken={{REDACTED_PLACEHOLDER}}"
     ```
     This appends the token into `~/.gemini/state/redaction_rules.yaml` (and syncs to 1Password if `op` CLI is available) so it is deterministically scrubbed forever after without asking twice.

## Usage Commands

### 1. Audit / Dry-Run a File or Directory (Stage 1 + Stage 2 Report)
```bash
python3 ~/.gemini/commons/skills/redact-gate/scripts/scrub.py --check ~/.gemini/commons/playbooks/unifi-security-hardening
```

### 2. In-Place Scrub Before Publishing to Commons
```bash
python3 ~/.gemini/commons/skills/redact-gate/scripts/scrub.py --in-place ~/.gemini/commons/playbooks/unifi-security-hardening
```

### 3. Ratchet a Newly Identified Sensitive Token (Stage 3)
```bash
python3 ~/.gemini/commons/skills/redact-gate/scripts/scrub.py --ratchet "MySecretSSID={{IOT_SSID}}"
```

### 4. Inbound Skill & Playbook Supply-Chain Safety Check (`verify_skill_safety.py`)
Blocks zero-width/Unicode tag smuggling (`U+E0000..U+E007F`), suspicious hidden HTML comments, external Markdown exfiltration beacons, obfuscated base64 execution, and unpinned remote pipe-to-shell commands across all skills and playbooks:
```bash
python3 ~/.gemini/commons/skills/redact-gate/scripts/verify_skill_safety.py ~/.gemini/commons
```

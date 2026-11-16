# Security & OPSEC Policy (`three-ring-agents/commons`)

## 1. Three-Ring OPSEC Boundary Invariant (`Ring 1 -> Ring 2 -> Ring 3`)
This repository (`three-ring-agents/commons`) is **Ring 3 (Public Open Source)**. It must never contain:
- **Ring 1 (`~/.gemini/state/`):** Credentials, OAuth tokens, 1Password `op://` service vault IDs, RFC1918 LAN IPs/CIDRs, MAC addresses, or family PII.
- **Ring 2 (`~/.gemini/mesh/`):** Live peer mesh project IDs, Google Chat space IDs, private Google Drive/Doc IDs, or named operator hardware overrides.

## 2. Mandatory Pre-Commit & CI Gates
Every pull request and commit to `three-ring-agents/commons` must pass two zero-dependency verification checks:
1. **Outbound 3-Stage Redaction Gate:**
   ```bash
   python3 skills/redact-gate/scripts/scrub.py --check .
   ```
2. **Inbound Skill Supply-Chain & V9 IPI Safety Verifier:**
   ```bash
   python3 skills/redact-gate/scripts/verify_skill_safety.py .
   ```

## 3. Reporting a Vulnerability or Accidental OPSEC Leak
If you discover a security vulnerability, prompt-injection vector, or accidental PII/topology leak, please open a private GitHub Security Advisory on `three-ring-agents/commons` rather than a public issue.

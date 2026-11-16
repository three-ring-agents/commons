# `three-ring-agents/commons` — Three-Ring Agent Commons (`~/.gemini/commons`)

Cross-harness agent skills, 3-Stage Outbound/Inbound OPSEC (`redact-gate` + `verify_skill_safety.py`), executable 3-section infrastructure playbooks, and zero-inbound-port peer federation templates.

## 1. The 3-Ring OPSEC Architecture (`Ring 1 -> Ring 2 -> Ring 3`)

> **Why 3 Rings? Preventing Cross-Surface Context Bleed:** Connecting a single flat-memory personal agent simultaneously to private accounts (banking, personal inbox, family schedules) and multi-person workspaces (Slack, peer chats, public GitHub) creates catastrophic cross-surface leakage—exemplified by real-world incidents where always-on agents posted private bank balances into shared workplace channels. Separating **Sovereign Local State (Ring 1)**, **Trusted Peer Mesh (Ring 2)**, and **Public Commons (Ring 3)** with deterministic outbound/inbound gates eliminates flat-context bleed by construction.

| Ring | Mount Path & Visibility | Purpose |
| :--- | :--- | :--- |
| **🟢 Ring 3: Public Commons** *(This Repo)* | `~/.gemini/commons` (`three-ring-agents/commons`, Apache-2.0) | Reusable cross-harness skills (`skills/`), parameterized templates (`templates/`), 3-section infrastructure playbooks (`playbooks/`), and anonymous hardware stack profiles (`profiles/`). |
| **🟡 Ring 2: Private Peer Mesh** | `~/.gemini/mesh` (`<org>/dttw-mesh` + Drive `dttw-mesh.bundle`) | Shared peer mesh coordinates (`mesh.json`: Pub/Sub project/topic, Google Chat space IDs, shared Drive/Doc IDs) and named peer overrides (`variants/<peer>/`). |
| **🔴 Ring 1: Sovereign Local State** | `~/.gemini/state` (Local `0600` Only) | Personal `config.json`, OAuth tokens, 1Password `op://` secret pointers, LAN subnets/VLANs, and personal `redaction_rules.yaml`. |

## 2. Repository Structure

```text
~/.gemini/commons/
├── README.md
├── LICENSE                                  # Apache-2.0 License
├── SECURITY.md                              # 3-Ring OPSEC & Vulnerability Policy
├── .pre-commit-config.yaml                  # Local pre-commit hooks (scrub.py + verify_skill_safety.py)
├── install-commons-local.sh                 # Symlinks skills into ~/.gemini/antigravity-cli/skills/, ~/.agents/skills/, and ~/.claude/skills/
├── skills/
│   ├── collab-roe/                          # Shared Rules of Engagement & Google Docs native Kix commenting
│   ├── gchat/                               # Dual-Identity Google Chat CLI (--send-as agent & --send-as human)
│   ├── poppy-client/                        # 100% Python stdlib Personal Agent Protocol (Poppy v1.0) client & exact-terms operations
│   ├── redact-gate/                         # 3-Stage Outbound Redaction Gate (scrub.py) + Inbound V9 IPI Verifier (verify_skill_safety.py)
│   └── sync-commons/                        # Dual GitHub + Drive bundle sync with 3-Stage Redaction Gate
├── templates/
│   ├── state-sync-starter/                  # Parameterized ~/.gemini/state & ~/.gemini/mesh starter templates
│   ├── supervised-intent-gatekeeper/        # Sanitized <18 Supervised Family Intent Gatekeeper blueprint
│   └── pubsub-wake-wire/                    # GCP Pub/Sub listen_once.py + Two-Room Google Chat spec
├── profiles/
│   ├── macos-catalina-legacy/               # Dedicated Intel Mac Mini (Catalina) + FDA Launcher + Strike 1-3 Alerting
│   └── macos-proxmox-unifi/                 # Apple Silicon Mac mini + Proxmox VE LXC + Cloudflare Workers Edge DMS
└── playbooks/
    ├── PLAYBOOK_TEMPLATE.md                 # Standard 3-section Playbook (Intent, Pitfalls, Verification Probes)
    ├── chief-of-staff/                      # Sovereign Personal Agent / Chief of Staff + Out-of-Model Gate + tau-bench
    ├── host-infrastructure-and-telemetry/   # Multi-Host Supervision, storagekitd Guard & 3-Tier Self-Healing
    ├── multi-model-credit-waterline/        # Multi-Model Utility Routing & $100/mo GCP Credit Waterline Controller
    ├── plan-bound-mpa-and-secret-isolation/ # Plan-Bound MPA (mpad), Per-Call AoD & 1Password Vault Isolation
    ├── unifi-security-hardening/            # UniFi VLAN, Firewall & Relational SLO-4 Hardening
    ├── zero-clutter-daemon-iac/             # Turnkey launchd/systemd Daemon IaC Compiler & Cross-Thread Leases
    └── zero-port-poppy-identity/            # Zero-Port Personal Agent Protocol (Poppy v1.0) Federation & 7-Point Audit
```

## 3. Quick Start & Verification Gates

```bash
# 1. Install skills across Antigravity CLI, ~/.agents/skills, and ~/.claude/skills
./install-commons-local.sh

# 2. Verify Outbound 3-Stage Redaction Gate (0 private tokens or Stage 2 ambiguities)
python3 skills/redact-gate/scripts/scrub.py --check .

# 3. Verify Inbound V9 IPI Supply-Chain Safety (0 hidden Unicode tags, beacons, or unpinned pipe-to-shell)
python3 skills/redact-gate/scripts/verify_skill_safety.py .
```

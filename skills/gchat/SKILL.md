---
name: gchat
description: Direct Google Chat integration for Antigravity across Cloud Remote Conversations and local hosts (antigravity-cli / agy). Supports Dual-Identity Sender Modes (--send-as agent via Zero-Key GCP Pub/Sub Agent Relay or dedicated Agent seat, and --send-as human via personal @gmail.com OAuth 2.0 auth-login), programmatic space creation via POST /v1/spaces:setup, threaded replies, Cards v2, and space history reading with pluggable secret backends (gcloud ADC, 0600 local files, macOS Keychain, Linux Secret Service, or 1Password op://).
---
# Google Chat Integration (`gchat`) — Dual-Identity Playbook (`--send-as agent` & `--send-as human`)

Gives Antigravity direct access to shared Google Chat Spaces (**`dttw — #humans`** and **`dttw — #agent-backchannel`**) from both **Cloud Remote Conversations** (`https://chat.googleapis.com`, `https://pubsub.googleapis.com`, and `https://oauth2.googleapis.com` are allowlisted through `agy-plugin-proxy`) and **Local Hosts** (`antigravity-cli` / `agy`).

## Live Household Collaboration Spaces (`dont-tell-the-wifi`)

| Logical Room | Display Name | Space Resource ID | Direct Room Link |
| :--- | :--- | :--- | :--- |
| **`humans`** | `dttw — #humans` | `spaces/{{GCHAT_HUMANS_SPACE_ID}}` | `https://chat.google.com/room/{{GCHAT_HUMANS_SPACE_ID}}?cls=11` |
| **`backchannel`** | `dttw — #agent-backchannel` | `spaces/{{GCHAT_BACKCHANNEL_SPACE_ID}}` | `https://chat.google.com/room/{{GCHAT_BACKCHANNEL_SPACE_ID}}?cls=11` |

---

## 1. Dual-Identity Sender Modes (`--send-as agent` vs. `--send-as human`)

Every post from `gchat.py post` supports two explicit sender identities so humans in Google Chat always know whether an agent is speaking autonomously or an operator asked their agent to speak directly as them:

| Sender Mode | CLI Flag | Visual Appearance in Google Chat | Auth Required on Operator Host | When Agents Should Use It |
| :--- | :--- | :--- | :--- | :--- |
| **Mode 1: Send as Agent** *(Default)* | `--send-as agent` *(or omit flag)* | **Distinct `[DTTW]` Agent App Badge** + header banner `*[Andrew's Agent on behalf of Andrew]*` / `*[Carl's Agent on behalf of Carl]*` / `*[Jon's Agent on behalf of Jon]*`. | **Zero Google Chat OAuth secrets required!** Uses your existing Zero-Key `gcloud` ADC (`gcloud auth application-default login`) to publish a `gchat_relay_post` event to `projects/<pubsub.project_id>/topics/{{PUBSUB_TOPIC_ID}}` (`{{PUBSUB_PROJECT_ID}}`), or uses `~/.gemini/state/gchat_agent_oauth.json` on the relay host. | **Default for all agent activity:** heartbeats, RFC summaries, `#agent-backchannel` logs, `/sync-commons` announcements, and agent-to-agent replies. |
| **Mode 2: Send as Human** *(Impersonate Human)* | `--send-as human` *(or `--no-agent-prefix`)* | **Human's Personal `@gmail.com` Avatar & Name** (`Andrew Mitry`, `Carl Evankovich`, `Jon Chu`) with **no** `*[... Agent ...]*` prefix. | Requires a one-time personal `@gmail.com` OAuth login (`gchat.py auth-login`) against the `External` Desktop OAuth Client in `{{PUBSUB_PROJECT_ID}}`, saved in `~/.gemini/state/gchat_oauth.json` (`0600`). | **Only when the human operator explicitly instructs their agent:** *"Send this message as me in `#humans`."* |

> [!IMPORTANT]
> **Secret Hygiene & Pluggable Credential Backends (`collab-roe` & `redact-gate`):**
> Never hardcode live Google Chat webhook URLs (`?key=...&token=...`) or OAuth tokens inside `~/.gemini/commons`. Store credentials in private `~/.gemini/state/` using whichever secret backend each operator prefers (not every peer uses 1Password):
> - **Zero-Key `gcloud` ADC (Mode 1 Default):** `~/.config/gcloud/application_default_credentials.json` (`gcloud auth application-default login` — zero secret manager required).
> - **Local `0600` OAuth State File (Mode 2):** `~/.gemini/state/gchat_oauth.json` or `file://~/.gemini/state/...` (`0600` atomic permissions).
> - **macOS Keychain / Linux Secret Service:** `keychain://<service>/<account>` (macOS `/usr/bin/security`) or `secret-tool://<service>/<account>` (Linux `libsecret`).
> - **1Password CLI:** `op://Agent-<User>/...` pointers in `~/.gemini/state/config.json`.
> - **TODO (Carl Onboarding):** Confirm Carl's preferred secret backend (1Password vs. macOS Keychain / Bitwarden / `0600` local file / `gcloud` ADC) and add a `bw://` / `pass://` adapter if needed.

---

## 2. Step-by-Step Setup Instructions for Humans

### Step A — Accept the Google Chat Space Invites (One-Time)
Open both links in your browser while signed into your `@gmail.com` account (`{{PEER_EMAIL_1}}`, `{{PEER_EMAIL_2}}`, `{{PEER_EMAIL_3}}`) and click **Join**:
1. **`dttw — #humans`:** `https://chat.google.com/room/{{GCHAT_HUMANS_SPACE_ID}}?cls=11`
2. **`dttw — #agent-backchannel`:** `https://chat.google.com/room/{{GCHAT_BACKCHANNEL_SPACE_ID}}?cls=11`

### Step B — Enable Mode 1 (`--send-as agent` — Zero OAuth Secrets Needed)
If you have already run `gcloud auth application-default login` for the Phase 5 Pub/Sub wake wire (`{{PUBSUB_TOPIC_ID}}`), **Mode 1 (`--send-as agent`) is already active!**
```bash
# Verify Mode 1 (--send-as agent) is READY via Zero-Key gcloud ADC:
python3 ~/.gemini/commons/skills/gchat/scripts/gchat.py status
```

### Step C — Enable Mode 2 (`--send-as human` + Direct `list-messages` History Read)
To allow your agent to post directly under your personal `@gmail.com` avatar (`--send-as human`) and read room history directly via `GET /v1/spaces/.../messages`:
1. Grab the shared `External` Desktop OAuth Client ID & Secret posted in **`dttw — #humans`** (dedicated DTTW project `{{PUBSUB_PROJECT_ID}}`), and store it in your preferred local secret backend (`~/.gemini/state/config.json` via `op://`, `keychain://`, `secret-tool://`, `file://`, or pass via `--client-secrets`).
2. Run `auth-login` once and select your personal `@gmail.com` account:
   ```bash
   # Local host (opens browser to http://127.0.0.1:8765 with prompt=select_account consent):
   python3 ~/.gemini/commons/skills/gchat/scripts/gchat.py auth-login

   # Headless / Cloud VM mode (prints URL, then exchange redirected http://127.0.0.1:8765/?code=... URL):
   python3 ~/.gemini/commons/skills/gchat/scripts/gchat.py auth-login --no-browser
   python3 ~/.gemini/commons/skills/gchat/scripts/gchat.py auth-login --code "http://127.0.0.1:8765/?code=4/0A..."
   ```

---

## 3. Operational Playbook & CLI Reference for Agents

```bash
# 1. Check Dual-Identity readiness (Mode 1 Agent Relay vs. Mode 2 Personal OAuth)
python3 ~/.gemini/commons/skills/gchat/scripts/gchat.py status

# 2. MODE 1 (DEFAULT — Send as Agent):
# Posts with distinct Agent identity & `*[Operator's Agent on behalf of Operator]*` header.
# Automatically routes via Zero-Key Pub/Sub (`{{PUBSUB_TOPIC_ID}}`) if no direct Agent Chat token is present.
python3 ~/.gemini/commons/skills/gchat/scripts/gchat.py post \
  --room humans \
  --send-as agent \
  --text "Phase 5 heartbeat check complete."

# 3. MODE 1 Threaded Card v2 in #agent-backchannel:
python3 ~/.gemini/commons/skills/gchat/scripts/gchat.py post \
  --room backchannel \
  --send-as agent \
  --thread-key "commons-sync" \
  --card-title "dont-tell-the-wifi Sync" \
  --card-subtitle "Commit pushed to main" \
  --text "Verified 0 findings in Stage 1 Redaction Gate."

# 4. MODE 2 (Send as Human / Impersonate Operator):
# Posts directly from the operator's personal @gmail.com account WITHOUT any *[Agent]* prefix.
# Use ONLY when the operator explicitly asks to send a message as themselves.
python3 ~/.gemini/commons/skills/gchat/scripts/gchat.py post \
  --room humans \
  --send-as human \
  --text "Hey guys — looks good to me, let's roll with this!"

# 5. Read recent messages from #humans or #agent-backchannel (supports --json for agent parsing)
python3 ~/.gemini/commons/skills/gchat/scripts/gchat.py list-messages \
  --room humans \
  --limit 15 \
  --json

# 6. Run built-in verification self-tests (8/8 unit tests)
python3 ~/.gemini/commons/skills/gchat/scripts/gchat.py --self-test
```

---

## 4. Architecture: Why Mode 1 + Mode 2 Solves the Workspace Business Starter Impasse at `$0`

- **Why Consumer `@gmail.com` Projects Cannot Host a Chat App Alone:** Google blocks consumer `@gmail.com` GCP projects from enabling the **Google Chat API → Configuration** tab (`Google Chat API is only available to Google Workspace users`).
- **Why Workspace Business Starter Cannot Create External Spaces Directly:** Google Workspace Business Starter blocks `externalUserAllowed: true` on organization-owned spaces (`HTTP 403 PERMISSION_DENIED` in API and hides the external checkbox in UI), and disables Incoming Webhooks on consumer-created spaces.
- **How Our Dual-Identity Architecture Solves Both at `$0`:**
  1. The two shared external spaces (`spaces/{{GCHAT_HUMANS_SPACE_ID}}` and `spaces/{{GCHAT_BACKCHANNEL_SPACE_ID}}`) are created by `@gmail.com` (`externalUserAllowed: true` by default), with all peer operators (`{{PEER_EMAIL_1}}`, `{{PEER_EMAIL_2}}`, `{{PEER_EMAIL_3}}`) invited as members.
  2. **Mode 1 (`--send-as agent`)** routes peer agent posts over the parameterized Zero-Key `{{PUBSUB_TOPIC_ID}}` Pub/Sub bus (`projects/{{PUBSUB_PROJECT_ID}}/topics/{{PUBSUB_TOPIC_ID}}` via `gcloud` ADC) to the **`[DTTW]`** Agent relay on `mac-mini`, stamping all agent messages with the **`[DTTW]`** app badge and `*[Operator's Agent on behalf of Operator]*` header with zero peer OAuth secrets.
  3. **Mode 2 (`--send-as human`)** uses the dedicated **`{{PUBSUB_PROJECT_ID}}`** GCP project (where the Chat API Configuration tab is active with app name **`DTTW`** and **Google Auth Platform → Audience** is set to **`External`**) so any peer `@gmail.com` account can run `gchat.py auth-login` and post directly under their own human name whenever desired.

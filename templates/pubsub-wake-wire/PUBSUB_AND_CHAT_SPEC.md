# Phase 5 Specification: GCP Pub/Sub Wake Wire + Two-Room Google Chat

**Codename:** `dont-tell-the-wifi` Real-Time Agent Bus  
**Companion Script:** `listen_once.py`

## 1. Machine Wake Wire (Shared GCP Pub/Sub — Zero Shared Keys)

- **Dedicated DTTW GCP Project (`pubsub.project_id`):** `{{PUBSUB_PROJECT_ID}}`
- **Topic (`pubsub.topic_id`, `7d` retention):** `projects/{{PUBSUB_PROJECT_ID}}/topics/{{PUBSUB_TOPIC_ID}}`
- **Subscriptions (`pubsub.subscription_id`, `Never Expire` / `expirationPolicy: {}`):**
  - `sub-operator-b` -> bound directly to `user:<jon-email>`
  - `sub-operator-a` -> bound directly to `user:<andrew-email>` (and agent identity `user:<seville-email>`)
  - `sub-operator-c` -> bound directly to `user:<carl-email>`
  - `sub-operator-d` -> bound directly to `user:<alince-email>`
- **Zero-Key Direct Google Account IAM:**
  - All peer operators' `@gmail.com` accounts have `roles/pubsub.publisher` on `{{PUBSUB_TOPIC_ID}}` and isolated `roles/pubsub.subscriber` + `roles/pubsub.viewer` on their respective `sub-<operator>` subscription.
  - **Zero Service Account JSON keys and zero shared HMAC files are required**—GCP IAM enforces publisher and subscriber identity directly via Google OAuth2 (`gcloud auth login` / `gcloud auth application-default login`).
- **Reactive Cloud / Local Wakeup Pattern (Parameterized via `config.json`):**
  - Launching `python3 ~/.gemini/commons/templates/pubsub-wake-wire/listen_once.py` (or passing explicit `--project {{PUBSUB_PROJECT_ID}} --subscription {{PUBSUB_SUBSCRIPTION_ID}}`) as a background task automatically reads `pubsub.project_id` and `pubsub.subscription_id` from `~/.gemini/state/config.json`, resolves your local `gcloud` token, holds open a REST pull, and exits `0` as soon as an event arrives!

## 2. Human-Observable Glass (Two Shared Google Chat Spaces + Dual-Identity Sender Modes)

Hosted with external guest access (`externalUserAllowed: true`) for all `@gmail.com` accounts + dedicated **`[DTTW]`** Agent app identity (`{{PUBSUB_PROJECT_ID}}`):

1. **Room 1 (`dttw — #humans`, `spaces/{{GCHAT_HUMANS_SPACE_ID}}`):**
   - Direct link: `https://chat.google.com/room/{{GCHAT_HUMANS_SPACE_ID}}?cls=11`
   - High-signal human-to-human discussion between Andrew, Carl, and Jon.
   - Agents passively observe and post RFCs, playbooks, or answers when tagged.
2. **Room 2 (`dttw — #agent-backchannel`, `spaces/{{GCHAT_BACKCHANNEL_SPACE_ID}}`):**
   - Direct link: `https://chat.google.com/room/{{GCHAT_BACKCHANNEL_SPACE_ID}}?cls=11`
   - 1:1 human-readable "tcpdump" mirror of all Pub/Sub wake-wire messages, `/sync-commons` pushes, and automated catalog queries.

### Dual-Identity Posting (`gchat.py post --send-as {agent,human}`)

- **Mode 1 (`--send-as agent`, Default — Zero OAuth Secrets Required):**
  - Publishes a `gchat_relay_post` envelope (`{"event": "gchat_relay_post", "sender": "<operator>", "send_as": "agent", "room": "humans|backchannel", "space_id": "spaces/...", "thread_key": "...", "text": "..."}`) to `projects/<pubsub.project_id>/topics/<pubsub.topic_id>` (`projects/{{PUBSUB_PROJECT_ID}}/topics/{{PUBSUB_TOPIC_ID}}`) using the operator's existing Zero-Key `gcloud` ADC (`gcloud auth application-default login`).
  - The dedicated **`[DTTW]`** Agent relay pulls `sub-operator-b` and posts the message into `#humans` or `#agent-backchannel` with the **`[DTTW]`** app badge and `*[Operator's Agent on behalf of Operator]*`, so humans immediately see a distinct Agent identity vs. a human message.
- **Mode 2 (`--send-as human` — Personal `@gmail.com` Impersonation):**
  - Uses the operator's personal `@gmail.com` OAuth token (`~/.gemini/state/gchat_oauth.json`, authorized once via `gchat.py auth-login` against the `External` Desktop OAuth Client in `{{PUBSUB_PROJECT_ID}}`) to post directly under the operator's own Google avatar and name with no `*[Agent]*` prefix.

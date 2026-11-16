# Proactive Alerting Pattern (Strike 1-3 Escalation & Self-Healing)

Intent: operators are paged only for unresolved incidents; deterministic self-healing gets first chance.

| Stage | Trigger | Action | Operator alert |
|---|---|---|---|
| Strike 1 | first failed health check | Tier 1A deterministic fast-heal (0-15s) | suppressed |
| Strike 2 | second consecutive failure | Tier 1B agentic remediation (~60s) | suppressed |
| Strike 3 | third consecutive failure | Tier 2 page: messaging + Google Chat card | sent; 4h cooldown per unresolved incident |
| Recovery | status returns HEALTHY | automatic "All Clear" notification | sent once |
| Tier 3 | heartbeat stale >15 min | off-box dead-man's switch (3A Apps Script, or 3B Cloudflare Worker) | out-of-band |

Scope note: the `Terminal.app` FDA launcher is only needed for daemons reading TCC-protected local data (such as local `chat.db`). Pure HTTPS/OAuth workers run as standard headless `launchd`/`systemd` workers.

Pitfall: without alert suppression during heal, transient blips page the operator. Probe: simulate a failure and confirm no page until Strike 3, then confirm All Clear on recovery.

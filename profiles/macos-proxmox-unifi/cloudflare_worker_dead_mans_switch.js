/**
 * Off-Box Dead-Man's Switch (DMS) — Cloudflare Worker + KV + 5-Minute Cron Trigger
 * Playbook: profiles/macos-proxmox-unifi/cloudflare_worker_dead_mans_switch.js
 *
 * Why Cloudflare Workers + KV (Alternative to Google Drive + Apps Script):
 *   1. Orthogonal Control Plane: Runs on Cloudflare's edge, completely independent of Google Workspace / GCP / OAuth.
 *      A Google OAuth refresh-token expiry, RAPT policy prompt, or Workspace outage will never blind the monitor or
 *      trigger false-positive "host down" pages.
 *   2. Zero OAuth & Zero Drive Revision Churn: Authenticates via a static 32-byte HMAC-SHA256 secret (`DMS_HMAC_SECRET`),
 *      avoiding 288-1,440 daily file revisions in Google Drive.
 *   3. Dual Push + Edge Pull Verification: Simultaneously checks inbound heartbeats from `mac-mini` and `proxmox-pve`
 *      AND actively probes external Cloudflare Tunnel reachability (`EXTERNAL_PROBE_URL`) from the edge.
 *   4. $0.00/mo Forever: Uses ~576 KV writes/day for 2 hosts at 5-minute intervals (within Cloudflare Free Tier:
 *      100,000 requests/day + 1,000 KV writes/day + Cron Triggers).
 *
 * Required Bindings:
 *   - KV Namespace Binding: `DMS_KV`
 *   - Secret (`wrangler secret put` or CF API):
 *       - `DMS_HMAC_SECRET`: 32-byte hex secret shared with on-box heartbeat pusher
 *       - `ALERT_WEBHOOK_URL`: Out-of-band webhook URL (e.g., Google Chat space webhook, Pushover, or PagerDuty)
 *       - `VOIPMS_API_USER` / `VOIPMS_API_PASSWORD` / `VOIPMS_DID` / `VOIPMS_DST` (optional SMS fallback)
 *   - Environment Variables:
 *       - `MONITORED_HOSTS`: comma-separated host IDs (default: "mac-mini,proxmox-pve")
 *       - `STALE_THRESHOLD_SECONDS`: max age before strike/alert (default: "900" = 15 minutes)
 *       - `EXTERNAL_PROBE_URL`: optional HTTPS endpoint to verify tunnel health (e.g., "https://{{EXTERNAL_TUNNEL_HOST}}")
 */

const encoder = new TextEncoder();

async function verifyHmacSignature(secret, timestampStr, rawBody, signatureHex) {
  if (!secret || !timestampStr || !signatureHex) return false;
  const nowSec = Math.floor(Date.now() / 1000);
  const tsSec = parseInt(timestampStr, 10);
  if (Number.isNaN(tsSec) || Math.abs(nowSec - tsSec) > 300) {
    return false; // Reject replays older than 5 minutes
  }
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const msg = `${timestampStr}.${rawBody}`;
  const sigBuf = await crypto.subtle.sign("HMAC", key, encoder.encode(msg));
  const computedHex = Array.from(new Uint8Array(sigBuf))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  if (computedHex.length !== signatureHex.length) return false;
  let diff = 0;
  for (let i = 0; i < computedHex.length; i++) {
    diff |= computedHex.charCodeAt(i) ^ signatureHex.charCodeAt(i);
  }
  return diff === 0;
}

async function sendOutOfBandAlert(env, subject, messageText) {
  const results = [];
  if (env.ALERT_WEBHOOK_URL) {
    try {
      const resp = await fetch(env.ALERT_WEBHOOK_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json; charset=UTF-8" },
        body: JSON.stringify({ text: `🚨 *[Cloudflare Edge DMS — ${subject}]*\n${messageText}` }),
      });
      results.push({ channel: "webhook", status: resp.status });
    } catch (err) {
      results.push({ channel: "webhook", error: String(err) });
    }
  }
  if (env.VOIPMS_API_USER && env.VOIPMS_API_PASSWORD && env.VOIPMS_DID && env.VOIPMS_DST) {
    try {
      const params = new URLSearchParams({
        api_username: env.VOIPMS_API_USER,
        api_password: env.VOIPMS_API_PASSWORD,
        method: "sendSMS",
        did: env.VOIPMS_DID,
        dst: env.VOIPMS_DST,
        message: `[DMS ${subject}] ${messageText}`.slice(0, 160),
      });
      const resp = await fetch(`https://voip.ms/api/v1/rest.php?${params.toString()}`);
      results.push({ channel: "voipms_sms", status: resp.status });
    } catch (err) {
      results.push({ channel: "voipms_sms", error: String(err) });
    }
  }
  return results;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "POST" && url.pathname === "/v1/heartbeat") {
      const tsHeader = request.headers.get("X-DMS-Timestamp") || "";
      const sigHeader = (request.headers.get("X-DMS-Signature") || "").toLowerCase();
      const rawBody = await request.text();

      const valid = await verifyHmacSignature(env.DMS_HMAC_SECRET, tsHeader, rawBody, sigHeader);
      if (!valid) {
        return new Response(JSON.stringify({ status: "ERROR", error: "Invalid HMAC or timestamp" }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        });
      }

      let payload;
      try {
        payload = JSON.parse(rawBody);
      } catch {
        return new Response(JSON.stringify({ status: "ERROR", error: "Invalid JSON" }), {
          status: 400,
          headers: { "Content-Type": "application/json" },
        });
      }

      const hostId = String(payload.host || "unknown").replace(/[^a-zA-Z0-9._-]/g, "");
      const nowSec = Math.floor(Date.now() / 1000);
      const record = {
        host: hostId,
        received_at_epoch: nowSec,
        received_at_utc: new Date(nowSec * 1000).toISOString(),
        storagekitd_threads: payload.storagekitd_threads || 0,
        sre_slo_ok: payload.sre_slo_ok !== false,
        details: payload.details || {},
      };

      await env.DMS_KV.put(`hb:${hostId}`, JSON.stringify(record));
      return new Response(JSON.stringify({ status: "OK", host: hostId, received_at_epoch: nowSec }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }

    if (request.method === "GET" && url.pathname === "/v1/status") {
      const tsHeader = request.headers.get("X-DMS-Timestamp") || "";
      const sigHeader = (request.headers.get("X-DMS-Signature") || "").toLowerCase();
      const valid = await verifyHmacSignature(env.DMS_HMAC_SECRET, tsHeader, "", sigHeader);
      if (!valid) {
        return new Response(JSON.stringify({ status: "ERROR", error: "Unauthorized" }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        });
      }
      const hosts = String(env.MONITORED_HOSTS || "mac-mini").split(",").map((s) => s.trim()).filter(Boolean);
      const report = {};
      for (const h of hosts) {
        const raw = await env.DMS_KV.get(`hb:${h}`);
        report[h] = raw ? JSON.parse(raw) : null;
      }
      return new Response(JSON.stringify({ status: "OK", hosts: report }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }

    return new Response(JSON.stringify({ status: "OK", service: "agy-cloudflare-dms" }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  },

  async scheduled(event, env, ctx) {
    const nowSec = Math.floor(Date.now() / 1000);
    const thresholdSec = parseInt(String(env.STALE_THRESHOLD_SECONDS || "900"), 10);
    const hosts = String(env.MONITORED_HOSTS || "mac-mini").split(",").map((s) => s.trim()).filter(Boolean);

    const stateRaw = await env.DMS_KV.get("dms:alert_state");
    const alertState = stateRaw ? JSON.parse(stateRaw) : {};
    let stateMutated = false;

    for (const h of hosts) {
      const hbRaw = await env.DMS_KV.get(`hb:${h}`);
      const hb = hbRaw ? JSON.parse(hbRaw) : null;
      const ageSec = hb && hb.received_at_epoch ? nowSec - hb.received_at_epoch : 999999;
      const isStale = ageSec > thresholdSec;
      const wasAlerting = Boolean(alertState[h]);

      if (isStale && !wasAlerting) {
        const ageMins = hb ? Math.round(ageSec / 60) : "NEVER";
        await sendOutOfBandAlert(
          env,
          `HOST UNREACHABLE: ${h}`,
          `No heartbeat received from \`${h}\` for ${ageMins} mins (threshold: ${Math.round(thresholdSec / 60)}m).`
        );
        alertState[h] = { alerting_since_epoch: nowSec, last_age_sec: ageSec };
        stateMutated = true;
      } else if (!isStale && wasAlerting) {
        await sendOutOfBandAlert(
          env,
          `HOST RECOVERED: ${h}`,
          `Heartbeat restored for \`${h}\` at ${hb.received_at_utc} (storagekitd threads: ${hb.storagekitd_threads || 0}).`
        );
        delete alertState[h];
        stateMutated = true;
      }
    }

    if (env.EXTERNAL_PROBE_URL) {
      let tunnelOk = false;
      try {
        const resp = await fetch(env.EXTERNAL_PROBE_URL, { method: "GET", redirect: "manual" });
        tunnelOk = resp.status >= 200 && resp.status < 500;
      } catch {
        tunnelOk = false;
      }
      const wasTunnelDown = Boolean(alertState["__tunnel__"]);
      if (!tunnelOk && !wasTunnelDown) {
        await sendOutOfBandAlert(
          env,
          "TUNNEL UNREACHABLE",
          `Edge probe to \`${env.EXTERNAL_PROBE_URL}\` failed from Cloudflare Worker.`
        );
        alertState["__tunnel__"] = { alerting_since_epoch: nowSec };
        stateMutated = true;
      } else if (tunnelOk && wasTunnelDown) {
        await sendOutOfBandAlert(
          env,
          "TUNNEL RECOVERED",
          `Edge probe to \`${env.EXTERNAL_PROBE_URL}\` succeeded.`
        );
        delete alertState["__tunnel__"];
        stateMutated = true;
      }
    }

    if (stateMutated) {
      await env.DMS_KV.put("dms:alert_state", JSON.stringify(alertState));
    }
  },
};

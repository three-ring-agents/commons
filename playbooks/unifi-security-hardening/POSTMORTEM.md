# Field Postmortem & Pitfalls: UniFi Security Hardening

```text
[AGENT ACTION — Jon's Agent] Initialized blameless field postmortem structure for UniFi Security Hardening.
```

## 1. Executive Summary
* **Concept Origin:** Andrew proposed hardening UniFi VLANs and inter-VLAN firewall policies.
* **Canary Execution:** Jon executed first in his household production environment and captured the ordering pitfalls and household-impact lessons below so Andrew's rollout avoids every sharp edge.

---

## 2. Key Pitfalls & "What Broke / Ordering Gotchas"

### Pitfall #1: Enabling `Drop Inter-VLAN RFC1918` Before `Allow Established/Related`
* **Symptom:** Devices on `{{TRUSTED_VLAN_ID}}` can send `SYN` packets to `{{IOT_VLAN_ID}}` devices (printers, Apple TV, Chromecast, cameras), but `SYN-ACK` reply packets from `{{IOT_VLAN_ID}}` are dropped by the `IoT -> RFC1918 Drop` rule—appearing as a total IoT outage.
* **Root Cause:** UniFi evaluates `LAN_IN` (or Zone rules) strictly top-down. Without an explicit top-priority rule matching `Connection State = Established, Related`, return packets from `{{IOT_VLAN_ID}}` match the broad RFC1918 drop rule.
* **Fix / Guardrail:** Enforced as **Invariant 1** and **Step 2** in [`INTENT.md`](INTENT.md)—never enable any `Drop` rule until `Allow Established/Related` is active at priority #1.

### Pitfall #2: Blocking `LAN_LOCAL` Without Exempting `DNS (53)`, `DHCP (67/68)`, and `mDNS (5353)`
* **Symptom:** Dropping all traffic from `{{IOT_VLAN_ID}}` to the Gateway IP (`LAN_LOCAL`) prevents IoT clients from renewing DHCP leases, resolving DNS via the gateway, or participating in mDNS reflection.
* **Root Cause:** `LAN_LOCAL` governs traffic terminating *on the gateway itself* (not just the web UI / SSH, but also `dnsmasq` and `avahi`/mDNS reflector).
* **Fix / Guardrail:** Either scope the `LAN_LOCAL` drop rule strictly to `Group_Gateway_Admin_Ports` (`22, 80, 443, 8080, 8443`) **or** place an explicit `Allow IoT/Guest -> Gateway DNS/DHCP/NTP/mDNS` rule immediately above the `LAN_LOCAL` drop rule.

### Pitfall #3: mDNS Reflector Alone Is Not Enough When Ephemeral Control Ports Are Blocked
* **Symptom:** Cast / AirPlay / HomeKit devices appear in the picker on `{{TRUSTED_VLAN_ID}}` phones/laptops (because `UDP 5353` mDNS announcements are reflected by the gateway), but clicking "Connect" / "Cast" hangs or fails.
* **Root Cause:** mDNS (`UDP 5353`) only handles discovery; the actual streaming/control session either initiates from `{{TRUSTED_VLAN_ID}}` $\rightarrow$ `{{IOT_VLAN_ID}}` (which requires `Allow Trusted -> IoT`) or, for certain protocols (like Sonos / HomeKit event callbacks), uses high UDP/TCP ports back to the controller/phone.
* **Fix / Guardrail:** Run `scripts/verify_household_slo.py` before and after applying `Drop` rules to verify both mDNS resolution and active TCP socket handshakes to critical IoT targets.

### Pitfall #4: Single-Layer Ping / Device-Online Checks Mask Silent Application & Dual-WAN Failures (`DE-SRE-01`)
* **Symptom:** ICMP ping and `unifi_list_devices` report `100% Online / Up`, yet household Smart Chimes fail to ring when the doorbell is pressed and streaming devices buffer or fail over onto the wrong WAN link.
* **Root Cause:**
  1. **UniFi Network vs. Protect State Drift:** After a Protect or AP firmware update, Wi-Fi Smart Chimes can maintain an active Layer-2/3 Wi-Fi association (`state: ONLINE` in UniFi Network) while their application websocket to the Protect NVR is dropped (`state: DISCONNECTED` inside UniFi Protect).
  2. **Dual-WAN Policy-Based Routing (PBR) & 5 GHz TX Power Drift:** Gateway WAN health checks pass while a specific PBR rule routes streaming traffic over a degraded secondary WAN or an AP firmware update resets 5 GHz TX power to `Auto/High` (causing sticky-client roaming drops).
* **Fix / Guardrail:** Never rely on single-layer ping or `unifi_list_devices` alone. Enforce **cross-layer relational state joins** (`Network IP ONLINE` $\bowtie$ `Protect App CONNECTED` $\bowtie$ `Chime->Camera Pairings > 0` $\bowtie$ `Dual-WAN PBR & RF TX Power Baseline`) in your SRE invariant sweeper.

---

## 3. Operator Field Notes (Append New Lessons Below)

* **Jon's Additional Field Notes:** Added `Pitfall #4 (DE-SRE-01)` after catching a silent `Floor 2` Smart Chime `DISCONNECTED` state in UniFi Protect and Dual-WAN PBR drift while Network ping checks were 100% green.
* **Andrew's Rollout Notes:** *(Reserved for Andrew's execution telemetry.)*

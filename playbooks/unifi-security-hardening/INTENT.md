---
id: unifi-security-hardening
title: "UniFi Network & Inter-VLAN Firewall Security Hardening"
status: canaried
exposure_tier: admin-only
tags:
  - unifi
  - vlan
  - firewall
  - mdns
  - household-slo
lineage:
  concept_author: "andrew"
  first_prod_canary: "jon"
env_constraints:
  gateway_family: "UniFi Cloud Gateway / UDM / UXG"
  unifi_network_version: ">= 8.x / 9.x (Zone-Based or Traffic Rules / Classic LAN_IN)"
variable_manifest:
  UNIFI_HOST: "config.json:unifi.host"
  UNIFI_API_KEY: "op://Agent-{{OPERATOR}}/UniFi/api_key"
  MANAGEMENT_VLAN_ID: "config.json:unifi.vlans.management"
  TRUSTED_VLAN_ID: "config.json:unifi.vlans.trusted"
  IOT_VLAN_ID: "config.json:unifi.vlans.iot"
  GUEST_VLAN_ID: "config.json:unifi.vlans.guest"
---

# UniFi Security Hardening — Architectural Intent, Invariants & Household SLOs

## 1. Architectural Intent & Security Invariants (Required)

Regardless of whether the local household runs Classic Firewall Rules (`LAN_IN` / `LAN_LOCAL`) or Zone-Based Firewall policies in UniFi Network, the target end-state **must** satisfy five declarative invariants:

1. **Invariant 1 — Stateful Return Traffic First (Zero Self-Lockout):**
   * `Allow Established / Related` sessions **must** evaluate at the highest priority (`Rule #1` on `LAN_IN` / Inter-Zone matrix) *before* any inter-VLAN drop rule is enabled.
2. **Invariant 2 — Unidirectional Trusted $\rightarrow$ IoT Initiation:**
   * Principals on `{{TRUSTED_VLAN_ID}}` may initiate connections to devices on `{{IOT_VLAN_ID}}` (e.g., printers, HomeKit/Matter hubs, Apple TV, Chromecast, cameras), and `{{IOT_VLAN_ID}}` may reply via **Invariant 1**, but `{{IOT_VLAN_ID}}` **must never** initiate new TCP/UDP connections into `{{TRUSTED_VLAN_ID}}` or `{{MANAGEMENT_VLAN_ID}}`.
3. **Invariant 3 — Control-Plane / Gateway Management Lockdown (`LAN_LOCAL`):**
   * `{{IOT_VLAN_ID}}` and `{{GUEST_VLAN_ID}}` must be blocked from reaching the UniFi Gateway's management ports (`TCP 22`, `TCP 80`, `TCP 443`, `TCP 8080`, `TCP 8443`) on `LAN_LOCAL`, while explicitly allowing **DHCP (`UDP 67/68`)**, **DNS (`UDP/TCP 53`)**, **NTP (`UDP 123`)**, and **mDNS (`UDP 5353`)** (when Multicast DNS reflector is enabled).
4. **Invariant 4 — Scoped Cross-VLAN Discovery (mDNS / AirPlay / Google Cast):**
   * Multicast DNS (`mDNS` / IoT Auto-Discovery) is enabled strictly across `{{TRUSTED_VLAN_ID}}` and `{{IOT_VLAN_ID}}` (excluding `{{GUEST_VLAN_ID}}` and `{{MANAGEMENT_VLAN_ID}}`). Any explicit port pinholes required by discovery protocols (e.g., HomeKit/AirPlay ephemeral ports or Cast control) are scoped to specific device IP groups rather than opening all RFC1918 subnets.
5. **Invariant 5 — Admin Session Survivability:**
   * All mutations must be applied from a host whose management path is explicitly allowlisted (or out-of-band verified) prior to enabling `Drop Invalid` or `Drop Inter-VLAN RFC1918`.

---

## 2. Mandatory Execution Ordering (Anti-Lockout Sequence)

Agents and operators **must** apply configuration changes in this exact order:

1. **Step 0 — Run Pre-Flight Probes:** Execute `scripts/verify_household_slo.py --phase preflight` to baseline gateway latency, DNS resolution, internet reachability, and mDNS discovery.
2. **Step 1 — Define RFC1918 & Gateway Port Groups:**
   * `Group_RFC1918_Subnets`: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`
   * `Group_Gateway_Admin_Ports`: `22, 80, 443, 8080, 8443`
3. **Step 2 — Provision `Allow` Rules BEFORE Any `Drop` Rule:**
   * `LAN_IN` #1: **Allow Established & Related** (Source: Any $\rightarrow$ Dest: Any)
   * `LAN_IN` #2: **Allow Trusted VLAN $\rightarrow$ IoT VLAN** (New + Established/Related)
   * `LAN_LOCAL` #1: **Allow IoT/Guest Essential Gateway Services** (`DNS 53`, `DHCP 67-68`, `NTP 123`, `mDNS 5353`)
4. **Step 3 — Enable `Drop` Rules Last (One Rule at a Time with Probe Check):**
   * `LAN_LOCAL` #2: **Drop IoT & Guest $\rightarrow$ `Group_Gateway_Admin_Ports`**
   * `LAN_IN` #3: **Drop Invalid State**
   * `LAN_IN` #4: **Drop IoT & Guest $\rightarrow$ `Group_RFC1918_Subnets`**
5. **Step 4 — Run Post-Flight Probes:** Immediately run `scripts/verify_household_slo.py --phase postflight`. If any household SLO fails within 60 seconds, revert Step 3 immediately.

---

## 3. Household SLO & Verification Probes (Required)

Before marking any UniFi firewall change healthy, `scripts/verify_household_slo.py` verifies:

| SLO ID | Household Service | Probe / Verification Criteria | Target SLO |
| :--- | :--- | :--- | :--- |
| **SLO-1** | **Gateway & Controller Admin Access** | HTTPS `GET` to `{{UNIFI_HOST}}` from Trusted/Management host returns `200`/`302` in $<250\text{ ms}$. | $100\%$ reachable from Admin host |
| **SLO-2** | **DNS & Upstream Internet** | Resolve external domains via local gateway DNS and verify HTTPS reachability. | $<50\text{ ms}$ DNS latency |
| **SLO-3** | **Cross-VLAN Cast / AirPlay / Printer Discovery** | mDNS (`_googlecast._tcp.local`, `_airplay._tcp.local`, `_ipp._tcp.local`) resolves from `{{TRUSTED_VLAN_ID}}` to `{{IOT_VLAN_ID}}` targets. | Zero regression vs. pre-flight baseline |
| **SLO-4** | **IoT $\nrightarrow$ Gateway Admin Isolation** | From `{{IOT_VLAN_ID}}`, TCP connect to gateway `:443` / `:22` times out or resets, while `:53` (DNS) succeeds. | $100\%$ blocked on admin ports |

---

## 4. Peer Variants (`profiles/<archetype>/ or ~/.gemini/mesh/variants/<operator>/`)

* `~/.gemini/mesh/variants/jon/`: Add household-specific device group definitions or UniFi OS version notes after running `redact-gate`.
* `~/.gemini/mesh/variants/andrew/`: Add Andrew's gateway/version-specific notes or Terraform/API bindings.

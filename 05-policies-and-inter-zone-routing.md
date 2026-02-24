# Module 05 — Policies and Inter-Zone Routing

> **Goal:** Understand why zones alone are insufficient for multi-zone
> topologies, and how firewalld policies add directional, priority-ordered rules
> between zones. Master the HOST and ANY pseudo-zones, policy targets, and
> Policy Sets — the powerful RHEL 10 feature that pre-packages common
> configurations like gateways.

---

## Table of Contents

1. [The Limits of Zones Alone](#1-the-limits-of-zones-alone)
2. [What is a Policy?](#2-what-is-a-policy)
3. [Policy Anatomy](#3-policy-anatomy)
4. [Ingress and Egress Zones](#4-ingress-and-egress-zones)
5. [The HOST and ANY Pseudo-zones](#5-the-host-and-any-pseudo-zones)
6. [Policy Targets](#6-policy-targets)
7. [Policy Priority](#7-policy-priority)
8. [Policy Rules: Services, Ports, Rich Rules](#8-policy-rules-services-ports-rich-rules)
9. [Masquerading in Policies](#9-masquerading-in-policies)
10. [Policy Sets — New in firewalld 2.4 / RHEL 10](#10-policy-sets--new-in-firewalld-24--rhel-10)
11. [Zones vs Policies — When to Use Each](#11-zones-vs-policies--when-to-use-each)
12. [Policy XML Format](#12-policy-xml-format)
13. [Lab 5 — Three-Node DMZ Topology](#lab-5--three-node-dmz-topology)

---

## 1. The Limits of Zones Alone

Zones answer one question: *"What traffic is allowed to reach this host's
services from this network segment?"*

They do **not** answer: *"What traffic is allowed to pass through this host
from network A to network B?"*

Consider this topology:

```
Internet (172.20.1.0/24) ──── node1 ──── DMZ (172.20.2.0/24)
                          [eth0]   [eth1]
                        zone=public  zone=dmz
```

node1 is a gateway. You want:
1. Internet clients → DMZ web server (port 80): **ALLOW**
2. DMZ web server → Internet (outbound): **ALLOW**
3. DMZ web server → Internal LAN: **DENY**
4. Internet clients → Internal LAN directly: **DENY**

Zone rules on `public` zone only control traffic *destined for node1 itself*.
They don't control traffic that's merely *passing through* node1 from `public`
to `dmz`. That's what **policies** are for.

---

## 2. What is a Policy?

A **policy** is a directional set of rules that applies to traffic flowing
**between** two zones. It adds:

- **Direction** — traffic from zone A to zone B (one-way)
- **Target** — what to do with traffic that matches no specific rule
- **Rules** — services, ports, rich rules applied to this flow
- **Priority** — where in the overall rule chain this policy applies

Policies represent the inter-zone control plane. Zones represent the per-zone
access control plane.

```
Traffic flow: Internet → DMZ

Zone rule on 'public':     Controls: Can internet reach THIS HOST?
Policy (public → dmz):     Controls: Can internet pass THROUGH this host to DMZ?
Zone rule on 'dmz':        Controls: What can DMZ hosts do when they reach THIS HOST?
```

---

## 3. Policy Anatomy

A policy has:

| Property | Description |
|----------|-------------|
| **Name** | Unique identifier for the policy |
| **Ingress zones** | Zone(s) traffic is coming FROM |
| **Egress zones** | Zone(s) traffic is going TO |
| **Target** | Default verdict for unmatched traffic |
| **Priority** | Order relative to other policies and zones |
| **Rules** | Services, ports, rich rules, masquerade, forward-port |

```bash
# Create a policy
firewall-cmd --permanent --new-policy internet_to_dmz

# Set direction
firewall-cmd --permanent --policy internet_to_dmz --add-ingress-zone public
firewall-cmd --permanent --policy internet_to_dmz --add-egress-zone dmz

# Set what unmatched traffic does
firewall-cmd --permanent --policy internet_to_dmz --set-target REJECT

# Add allowed services
firewall-cmd --permanent --policy internet_to_dmz --add-service http
firewall-cmd --permanent --policy internet_to_dmz --add-service https

# Activate
firewall-cmd --reload

# Inspect
firewall-cmd --info-policy internet_to_dmz
```

---

## 4. Ingress and Egress Zones

Every policy has one or more **ingress zones** (where traffic comes from) and
one or more **egress zones** (where traffic is going to).

A policy applies to a packet if:
- The packet's source zone matches one of the ingress zones, **AND**
- The packet's destination zone matches one of the egress zones

```bash
# Multiple ingress zones (traffic from public OR external → dmz)
firewall-cmd --permanent --policy web_access --add-ingress-zone public
firewall-cmd --permanent --policy web_access --add-ingress-zone external

# Multiple egress zones (traffic from public → dmz OR internal)
firewall-cmd --permanent --policy outbound --add-egress-zone dmz
firewall-cmd --permanent --policy outbound --add-egress-zone ANY
```

> **📝 NOTE — Bidirectional is two policies**
> Policies are one-directional. If you want to allow traffic from A→B and B→A,
> you need two policies. This is intentional — it forces you to think about
> each direction explicitly.

---

## 5. The HOST and ANY Pseudo-zones

firewalld defines two special pseudo-zones that can be used in policies:

### `HOST`

Represents the firewall/gateway host itself. Traffic with `HOST` as the egress
zone is traffic destined **for the local machine's processes** (not forwarded).
Traffic with `HOST` as ingress is traffic **generated by the local machine**.

```
Policy: internal → HOST
Meaning: What can internal hosts do when they connect TO THIS HOST?
Example: Allow internal hosts to SSH into this gateway
```

```bash
# Allow internal hosts to manage this gateway via SSH
firewall-cmd --permanent --new-policy internal_to_host
firewall-cmd --permanent --policy internal_to_host --add-ingress-zone internal
firewall-cmd --permanent --policy internal_to_host --add-egress-zone HOST
firewall-cmd --permanent --policy internal_to_host --add-service ssh
firewall-cmd --permanent --policy internal_to_host --set-target REJECT
```

### `ANY`

A wildcard that matches any zone. Used when you want a rule to apply regardless
of the specific egress (or ingress) zone.

```
Policy: internal → ANY
Meaning: What can internal hosts do when they initiate any outbound connection?
Example: Allow internal hosts to reach anything (after masquerade)
```

```bash
# Allow all outbound traffic from internal zone (to anything)
firewall-cmd --permanent --new-policy internal_outbound
firewall-cmd --permanent --policy internal_outbound --add-ingress-zone internal
firewall-cmd --permanent --policy internal_outbound --add-egress-zone ANY
firewall-cmd --permanent --policy internal_outbound --set-target ACCEPT
```

### `ANY` as ingress

`ANY` as ingress means "traffic from any zone". Useful for rules that should
apply to all inbound traffic:

```bash
# Drop traffic from ANYWHERE to a specific zone
firewall-cmd --permanent --new-policy block_all_to_secret
firewall-cmd --permanent --policy block_all_to_secret --add-ingress-zone ANY
firewall-cmd --permanent --policy block_all_to_secret --add-egress-zone secret_zone
firewall-cmd --permanent --policy block_all_to_secret --set-target DROP
```

> **⚠️  IMPORTANT — HOST and ANY are not real zones**
> You cannot bind interfaces or sources to `HOST` or `ANY` — they only exist as
> targets in policy ingress/egress. Attempting to `--add-interface` to `HOST`
> will fail.

---

## 6. Policy Targets

The target defines what happens to packets that traverse this policy but don't
match any specific rule:

| Target | Behaviour |
|--------|-----------|
| `ACCEPT` | Forward all unmatched traffic |
| `REJECT` | Reject all unmatched traffic (ICMP error sent back) |
| `DROP` | Silently drop all unmatched traffic |
| `CONTINUE` | Don't make a decision; pass to next matching policy |

`CONTINUE` is the key to building layered policies. If a policy has target
`CONTINUE` and no rule matches, evaluation continues to the next policy.
This allows a general "baseline" policy and specific "exception" policies.

```bash
# Set target
firewall-cmd --permanent --policy mypolicy --set-target REJECT

# Check target
firewall-cmd --permanent --policy mypolicy --get-target
```

---

## 7. Policy Priority

When multiple policies could match a packet flow, **priority** determines which
one is evaluated first.

Priority is an integer. **Lower numbers run first.**

```bash
# Set priority (range: -32768 to 32767)
firewall-cmd --permanent --policy mypolicy --set-priority -100

# Check priority
firewall-cmd --permanent --policy mypolicy --get-priority
```

### Negative vs positive priorities

| Priority range | Evaluation order |
|----------------|-----------------|
| Negative (< 0) | **Before** zone rules |
| 0 | Same time as zone rules |
| Positive (> 0) | **After** zone rules |

This matters for precedence. A policy with priority `-100` runs before the zone
rules of any involved zone. A policy with priority `100` runs after zone rules.

### Default priority

If you don't set a priority, policies default to `-1` (just before zone rules).

### Practical example: exception before default drop

```bash
# High-priority exception: allow specific source through DROP policy
firewall-cmd --permanent --new-policy allow_admin_exception
firewall-cmd --permanent --policy allow_admin_exception --add-ingress-zone public
firewall-cmd --permanent --policy allow_admin_exception --add-egress-zone HOST
firewall-cmd --permanent --policy allow_admin_exception --set-priority -200
firewall-cmd --permanent --policy allow_admin_exception --add-rich-rule \
  'rule family="ipv4" source address="203.0.113.5" service name="ssh" accept'

# Lower-priority default: drop everything else
firewall-cmd --permanent --new-policy default_drop
firewall-cmd --permanent --policy default_drop --add-ingress-zone public
firewall-cmd --permanent --policy default_drop --add-egress-zone HOST
firewall-cmd --permanent --policy default_drop --set-priority -100
firewall-cmd --permanent --policy default_drop --set-target DROP

# Priority -200 (exception) runs BEFORE -100 (default drop)
```

---

## 8. Policy Rules: Services, Ports, Rich Rules

Policies support the same rule types as zones:

```bash
# Services
firewall-cmd --permanent --policy mypolicy --add-service http
firewall-cmd --permanent --policy mypolicy --remove-service http
firewall-cmd --permanent --policy mypolicy --list-services

# Ports
firewall-cmd --permanent --policy mypolicy --add-port 8080/tcp
firewall-cmd --permanent --policy mypolicy --list-ports

# Rich rules (Module 06 covers these in full detail)
firewall-cmd --permanent --policy mypolicy --add-rich-rule \
  'rule family="ipv4" source address="10.0.0.0/8" service name="http" accept'
firewall-cmd --permanent --policy mypolicy --list-rich-rules

# ICMP blocks
firewall-cmd --permanent --policy mypolicy --add-icmp-block echo-request
```

---

## 9. Masquerading in Policies

Masquerading (SNAT/NAT) can be enabled on policies, which is the preferred way
to configure NAT on RHEL 10 for multi-zone scenarios:

```bash
# Enable masquerading on the "internal to external" policy
firewall-cmd --permanent --new-policy nat_outbound
firewall-cmd --permanent --policy nat_outbound --add-ingress-zone internal
firewall-cmd --permanent --policy nat_outbound --add-egress-zone external
firewall-cmd --permanent --policy nat_outbound --set-target ACCEPT
firewall-cmd --permanent --policy nat_outbound --add-masquerade
firewall-cmd --reload
```

This replaces the older approach of enabling masquerade on a zone (which still
works, but policies give more control over which flows are masqueraded).

Port forwarding in policies follows the same syntax as zones:

```bash
firewall-cmd --permanent --policy nat_inbound \
  --add-forward-port port=80:proto=tcp:toport=8080:toaddr=172.20.2.20
```

---

## 10. Policy Sets — New in firewalld 2.4 / RHEL 10

**Policy Sets** are pre-packaged collections of policies for common use cases.
They are a RHEL 10 / firewalld 2.4+ feature.

### The gateway Policy Set

The most important Policy Set is `gateway`, which turns a host into a NAT
router by creating appropriate policies between the internal and external zones:

```bash
# List available policy sets
firewall-cmd --get-policy-sets

# Check if the gateway policy set is enabled or disabled
firewall-cmd --info-policy-set gateway

# Enable the gateway policy set (remove the 'disable' marker)
firewall-cmd --permanent --policy-set gateway --remove-disable
firewall-cmd --reload

# See what it created
firewall-cmd --list-all-policies
```

The gateway policy set creates:
- A policy for internal → external (with masquerade and ACCEPT)
- A policy for external → HOST (with REJECT for most, ACCEPT for established)
- Appropriate priorities for correct ordering

This replaces what previously required manually configuring masquerade and
multiple policies.

### Disabling a Policy Set

```bash
# Disable the gateway policy set
firewall-cmd --permanent --policy-set gateway --add-disable
firewall-cmd --reload
```

---

## 11. Zones vs Policies — When to Use Each

| Question | Use |
|----------|-----|
| "What can reach *this host's services* from the internet?" | Zone rule (public zone) |
| "What can pass *through* this host from zone A to zone B?" | Policy |
| "Can my VPN clients access the database on this host?" | Zone source binding + zone rules |
| "Can my DMZ servers reach the internet?" | Policy (dmz → external) |
| "Can containers on this host reach the internet?" | Policy (container zone → external) |
| "Can external hosts SSH into this host?" | Zone rule (public zone, add ssh service) |
| "Can internal hosts use this host as a gateway?" | Policy (internal → external + masquerade) |

The key distinction:
- **Zone rules** → traffic TO/FROM the host itself
- **Policy rules** → traffic THROUGH the host (forwarding/routing)

---

## 12. Policy XML Format

```xml
<?xml version="1.0" encoding="utf-8"?>
<policy priority="-1" target="CONTINUE">
  <short>Internet to DMZ</short>
  <description>Allow HTTP/HTTPS from internet to DMZ web servers.</description>

  <!-- Direction -->
  <ingress-zone name="public"/>
  <egress-zone name="dmz"/>

  <!-- Allowed services -->
  <service name="http"/>
  <service name="https"/>

  <!-- Raw ports -->
  <port protocol="tcp" port="8080"/>

  <!-- Rich rules -->
  <rule priority="0">
    <source address="192.0.2.0/24"/>
    <service name="http"/>
    <accept/>
  </rule>

  <!-- Masquerade (NAT) -->
  <masquerade/>

  <!-- Port forwarding -->
  <forward-port port="80" protocol="tcp" to-port="8080" to-addr="172.20.2.20"/>
</policy>
```

Location: `/etc/firewalld/policies/`

---

## Lab 5 — Three-Node DMZ Topology

**Topology:** Three-node (node1=gateway, node2=DMZ server, node3=internal client)

**Objective:** Build a realistic three-zone network. Configure policies so that:
- External clients (host) can reach the DMZ web server on port 80
- Internal clients (node3) can reach the DMZ web server on port 80
- Internal clients (node3) can reach the internet through node1
- The DMZ server cannot reach the internal network
- Direct internet access to internal hosts is blocked

---

### Step 1 — Start all three nodes

```bash
# 🔧 LAB STEP (on host)
~/firewalld-lab/start-lab.sh
# Or manually:
# See Module 00 section 6.3 for the three-node start commands
sleep 8  # Wait for systemd + firewalld on all nodes
```

---

### Step 2 — Configure node1's zone assignments

```bash
# 🔧 LAB STEP (inside node1)
podman exec -it node1 bash

# Check what interfaces we have
ip link show | grep "eth[0-9]"

# Assign zones
# eth0 → external (internet-facing, with masquerade)
# eth1 → dmz
# eth2 → internal
firewall-cmd --permanent --zone=external --add-interface=eth0
firewall-cmd --permanent --zone=dmz --add-interface=eth1
firewall-cmd --permanent --zone=internal --add-interface=eth2

# Remove them from public if they were auto-assigned
firewall-cmd --permanent --zone=public --remove-interface=eth0 2>/dev/null || true
firewall-cmd --permanent --zone=public --remove-interface=eth1 2>/dev/null || true
firewall-cmd --permanent --zone=public --remove-interface=eth2 2>/dev/null || true

firewall-cmd --reload
firewall-cmd --get-active-zones
```

---

### Step 3 — Enable IP forwarding on node1

```bash
# 🔧 LAB STEP (inside node1)
# Check current status
sysctl net.ipv4.ip_forward

# Enable (runtime — sufficient for this lab; the container restarts clean anyway)
sysctl -w net.ipv4.ip_forward=1

# Permanent inside the container (persists across firewalld reloads but NOT
# across container restarts — on a real host this would survive reboots)
echo "net.ipv4.ip_forward=1" >> /etc/sysctl.d/99-ip-forward.conf
```

---

### Step 4 — Start a web server on node2 (DMZ)

```bash
# 🔧 LAB STEP (inside node2)
podman exec -it node2 bash
python3 -m http.server 80 &
# Allow HTTP on node2's firewall
firewall-cmd --zone=public --add-service=http
```

---

### Step 5 — Set default routes on node2 and node3

```bash
# 🔧 LAB STEP (inside node2)
# node2's default route should be through node1's DMZ interface
ip route add default via 172.20.2.10

# 🔧 LAB STEP (inside node3)
podman exec -it node3 bash
ip route add default via 172.20.3.10
```

---

### Step 6 — Create policy: external → DMZ (web traffic)

```bash
# 🔧 LAB STEP (inside node1)
podman exec -it node1 bash

firewall-cmd --permanent --new-policy ext_to_dmz
firewall-cmd --permanent --policy ext_to_dmz --add-ingress-zone external
firewall-cmd --permanent --policy ext_to_dmz --add-egress-zone dmz
firewall-cmd --permanent --policy ext_to_dmz --set-target REJECT
firewall-cmd --permanent --policy ext_to_dmz --add-service http
firewall-cmd --reload

# Test (from host)
curl -m 3 http://172.20.2.20/
# Should succeed
```

---

### Step 7 — Create policy: internal → external (with masquerade)

```bash
# 🔧 LAB STEP (inside node1)

firewall-cmd --permanent --new-policy int_to_ext
firewall-cmd --permanent --policy int_to_ext --add-ingress-zone internal
firewall-cmd --permanent --policy int_to_ext --add-egress-zone external
firewall-cmd --permanent --policy int_to_ext --set-target ACCEPT
firewall-cmd --permanent --policy int_to_ext --add-masquerade
firewall-cmd --reload
```

---

### Step 8 — Create policy: internal → DMZ

```bash
# 🔧 LAB STEP (inside node1)

firewall-cmd --permanent --new-policy int_to_dmz
firewall-cmd --permanent --policy int_to_dmz --add-ingress-zone internal
firewall-cmd --permanent --policy int_to_dmz --add-egress-zone dmz
firewall-cmd --permanent --policy int_to_dmz --set-target REJECT
firewall-cmd --permanent --policy int_to_dmz --add-service http
firewall-cmd --reload

# Test from node3 (internal client)
# (inside node3)
curl -m 3 http://172.20.2.20/
# Should succeed
```

---

### Step 9 — Verify DMZ cannot reach internal

```bash
# 🔧 LAB STEP (inside node2)

# No policy exists for dmz → internal, so traffic should be blocked
# Try to reach node3 from node2
curl -m 3 http://172.20.3.30/ 2>&1
# Should timeout or be rejected
```

> **💡 CONCEPT CHECK**
> Without an explicit `dmz → internal` policy, there is no path for traffic
> to flow. The default policy between zones not covered by an explicit policy
> is to drop/reject (depending on zone targets). This is the principle of
> **least privilege by default** — traffic is denied unless explicitly permitted.

---

### Step 10 — List all policies

```bash
# 🔧 LAB STEP (inside node1)
firewall-cmd --list-all-policies
firewall-cmd --info-policy ext_to_dmz
firewall-cmd --info-policy int_to_ext
firewall-cmd --info-policy int_to_dmz
```

---

### Step 11 — Look at nftables to see policy rules

```bash
# 🔧 LAB STEP (inside node1)

# Policies appear as chains in nftables
nft list table inet firewalld | grep policy

# Look at a specific policy chain
nft list chain inet firewalld filter_FWD_policy_ext_to_dmz
```

---

### Clean up

```bash
# 🔧 LAB STEP (inside node1)
for policy in ext_to_dmz int_to_ext int_to_dmz; do
  firewall-cmd --permanent --delete-policy $policy 2>/dev/null || true
done
firewall-cmd --reload
```

```bash
# On host
podman stop node1 node2 node3
```

---

### Summary

| Policy created | Purpose |
|----------------|---------|
| `ext_to_dmz` | Internet → DMZ web servers (HTTP only) |
| `int_to_ext` | Internal → Internet (with masquerade for NAT) |
| `int_to_dmz` | Internal → DMZ (HTTP only, lateral access to web servers) |
| *(none)* | DMZ → Internal: implicitly blocked (no policy = no path) |

---

*Module 05 complete.*

**Continue to [Module 06 — Rich Rules →](./06-rich-rules.md)**

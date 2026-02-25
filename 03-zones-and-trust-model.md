# Module 03 — Zones and the Trust Model

> **Goal:** Understand every predefined firewalld zone, the conceptual trust
> model they represent, how traffic is assigned to zones (interface binding vs
> source binding, and their precedence), and how to create and manage custom
> zones. Zones are the primary organisational unit of firewalld — everything
> else builds on top of them.

---

## Table of Contents

1. [1. The Zone Mental Model](#1-the-zone-mental-model)
2. [2. How Traffic Is Assigned to a Zone](#2-how-traffic-is-assigned-to-a-zone)
3. [3. Interface Binding vs Source Binding](#3-interface-binding-vs-source-binding)
4. [4. Binding Precedence](#4-binding-precedence)
5. [5. The Nine Predefined Zones](#5-the-nine-predefined-zones)
6. [6. Zone Targets](#6-zone-targets)
7. [7. The Default Zone](#7-the-default-zone)
8. [8. Creating and Managing Custom Zones](#8-creating-and-managing-custom-zones)
9. [9. Zone XML Format](#9-zone-xml-format)
10. [10. Intra-zone Forwarding](#10-intra-zone-forwarding)
11. [11. Zone Inspection Commands](#11-zone-inspection-commands)
12. [Lab 3 — Custom Zones and Interface Binding](#lab-3-custom-zones-and-interface-binding)

---

↑ [Back to TOC](#table-of-contents)

## 1. The Zone Mental Model

A **zone** is a named trust level that you assign to network traffic. The name
is a label for your policy intent. The rules inside the zone define what is
allowed or denied.

Think of zones as physical security zones in a building:

```
┌────────────────────────────────────────────────────────┐
│                  HIGH SECURITY ZONE                    │
│   (internal network — trusted staff, no restrictions)  │
│                                                        │
│  ┌─────────────────────────────────────────────────┐   │
│  │           MEDIUM SECURITY ZONE                  │   │
│  │     (DMZ — limited, verified services only)     │   │
│  │                                                 │   │
│  │  ┌────────────────────────────────────────┐     │   │
│  │  │        LOW SECURITY ZONE               │     │   │
│  │  │  (external/internet — untrusted,        │     │   │
│  │  │   minimal access permitted)             │     │   │
│  │  └────────────────────────────────────────┘     │   │
│  └─────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────┘
```

**Key principle:** A zone defines what traffic is *allowed to reach the host*
or *be forwarded* when it arrives on a particular interface or from a particular
source. The zone does not describe where traffic is *going* — policies handle
that (Module 05).

A packet has exactly ONE zone. There is no concept of a packet entering one zone
and leaving another within the zone logic itself. The zone is determined at
ingress based on the packet's source interface or source IP address.

---

↑ [Back to TOC](#table-of-contents)

## 2. How Traffic Is Assigned to a Zone

Every packet processed by firewalld is assigned to exactly one zone. The
assignment rules are:

### 1. Source-based assignment (checked first)
If the packet's source IP address matches a source CIDR or IP address explicitly
bound to a zone, that zone is used.

### 2. Interface-based assignment (checked second)
If no source binding matches, the zone bound to the ingress interface is used.

### 3. Default zone (fallback)
If the ingress interface is not bound to any zone, the **default zone** is used.

```
Incoming packet
│
├─ Does source IP match a zone source binding?
│   YES → Use that zone
│   NO  ↓
│
├─ Does the ingress interface belong to a zone?
│   YES → Use that zone
│   NO  ↓
│
└─ Use the default zone
```

---

↑ [Back to TOC](#table-of-contents)

## 3. Interface Binding vs Source Binding

### Interface binding

An interface binding associates a network interface with a zone. All traffic
arriving on that interface belongs to that zone (unless overridden by a more
specific source binding).

```bash
# Bind eth0 to the internal zone (permanent)
firewall-cmd --permanent --zone=internal --add-interface=eth0

# Bind eth1 to the public zone
firewall-cmd --permanent --zone=public --add-interface=eth1

# Check current bindings
firewall-cmd --get-active-zones
```

Interface bindings are typically managed by NetworkManager. When you assign a
connection to a firewalld zone in NetworkManager, it handles the binding. On
RHEL 10, the recommended approach for server configurations is via NetworkManager
connections:

```bash
# Set the firewalld zone for a NetworkManager connection
nmcli connection modify "Wired connection 1" connection.zone internal
```

### Source binding

A source binding associates a CIDR range or specific IP address with a zone.
Packets from matching sources use that zone **regardless of which interface they
arrive on**.

```bash
# All traffic from 10.10.0.0/16 is treated as internal, regardless of interface
firewall-cmd --permanent --zone=internal --add-source=10.10.0.0/16

# Traffic from a specific management IP gets admin zone access
firewall-cmd --permanent --zone=trusted --add-source=192.168.100.5/32

# Verify source bindings
firewall-cmd --get-active-zones
```

Source bindings are powerful for:
- Multi-homed servers where one interface carries multiple types of traffic
- VPN tunnels (the VPN client IP range gets internal zone treatment)
- Container networks (all container traffic gets its own zone)

---

↑ [Back to TOC](#table-of-contents)

## 4. Binding Precedence

When a packet could match multiple zones (an interface binding AND a source
binding), **source binding wins**.

Example: eth0 is in the `public` zone. A source binding puts 10.10.0.0/16 in
the `internal` zone. A packet arrives on eth0 from 10.10.1.5:

```
Packet: source=10.10.1.5, ingress interface=eth0

Check source binding: 10.10.1.5 ∈ 10.10.0.0/16 → zone=internal ✓
(interface binding eth0→public is ignored)

Result: packet processed by internal zone rules
```

This is the mechanism that makes VPNs work naturally: VPN traffic arrives on
the physical interface (say, `eth0` in `public` zone), but the VPN client IP
range has a source binding to `internal`, so VPN clients get appropriate access.

> **⚠️  IMPORTANT — Source binding specificity**
> If two source bindings overlap (e.g., 10.0.0.0/8 in zone A and 10.10.0.0/16
> in zone B), the more specific (longer prefix) match wins. A packet from
> 10.10.5.1 uses zone B, not zone A.

---

↑ [Back to TOC](#table-of-contents)

## 5. The Nine Predefined Zones

These zones are shipped with firewalld and cover the vast majority of use cases.
They are ordered from most restrictive to most permissive:

### `drop` — Silent discard

```
Default target: DROP
Inbound: All packets silently discarded
Outbound: Allowed
```

Every incoming packet is dropped with no reply. Connections don't "fail" —
they just time out. This is the most aggressive zone for untrusted networks.

**Use when:** You want to completely ignore all inbound traffic from a source —
for example, binding a known-malicious IP range to this zone via source binding.

```bash
# Example: silently drop all traffic from a hostile range
firewall-cmd --permanent --zone=drop --add-source=198.51.100.0/24
```

> **💡 Why silent drop instead of reject?**
> Dropping silently prevents attackers from learning that the host exists —
> a `reject` sends back an ICMP error, confirming the host is alive. Dropping
> also prevents your system from being used to amplify traffic back to a spoofed
> source. However, silent drops make debugging harder (timeouts instead of
> immediate errors), so only use `drop` for genuinely hostile traffic.

### `block` — Reject with ICMP error

```
Default target: REJECT
Inbound: Rejected with icmp-host-prohibited (IPv4)
         or icmp6-adm-prohibited (IPv6)
Outbound: Allowed
```

Similar to `drop` but sends back an ICMP "administratively prohibited" error.
The connection fails immediately instead of timing out, which is more honest
to the connecting client but reveals the host's existence.

**Use when:** You want to clearly communicate "this is not allowed" to
legitimate (but unauthorised) clients — better user experience than a timeout.

### `public` — Untrusted public networks (default)

```
Default target: default (reject/deny unlisted)
Default services: ssh, cockpit, dhcpv6-client
```

For use with public networks where you don't trust other machines. Only
explicitly allowed services are permitted. This is the default zone for most
RHEL server configurations and is the appropriate zone for internet-facing
interfaces.

**Use when:** Your interface faces the internet, a shared hosting network, or
any network where you don't control the other machines.

### `external` — External network with masquerading

```
Default target: default
Default services: ssh
Masquerade: YES (enabled by default)
```

Designed specifically for the **external interface of a router or gateway**.
Masquerading is enabled by default, which means traffic forwarded through this
interface has its source address rewritten to the interface's IP. This is
exactly what NAT routers do.

**Use when:** This interface is the WAN (internet-facing) side of a router.
Pair it with an internal or home zone on the LAN side.

> **📝 NOTE — external vs public**
> Both are "untrusted" zones, but `external` has masquerading enabled by default.
> If you're building a gateway, `external` is semantically correct. If you're
> building a server, `public` is the right choice even if the server has a
> public IP — servers don't masquerade.

### `dmz` — Demilitarised zone

```
Default target: default
Default services: ssh
```

For computers in the DMZ — accessible from the internet but isolated from your
internal network. Limited access to the internal network is possible through
policies (Module 05) but not automatic.

**Use when:** Servers that must be accessible from both the internet and
internal networks but should not have full internal network access — web servers,
reverse proxies, bastion hosts.

### `work` — Trusted workplace networks

```
Default target: default
Default services: dhcpv6-client, ipp-client, ssh
```

For use in work environments. Machines in the same network are generally trusted,
more services are allowed than in `public`.

**Use when:** Workstations on a corporate LAN where colleagues' machines are
considered relatively trustworthy.

### `home` — Trusted home networks

```
Default target: default
Default services: dhcpv6-client, mdns, ipp-client, samba-client, ssh
```

For home networks. More permissive than `work`, includes mDNS (for Bonjour/
Avahi service discovery) and Samba client (for Windows file sharing).

**Use when:** Home or small office networks where all devices are your own.

### `internal` — Internal LAN (most permissive named zone)

```
Default target: default
Default services: dhcpv6-client, mdns, ipp-client, samba-client, ssh
```

For the internal side of a gateway or for internal LAN interfaces. Same default
services as `home` but semantically distinct — `internal` implies it's the
trusted LAN of a multi-interface device.

**Use when:** The LAN interface of a gateway/router, or your internal server
network where all hosts are company-owned and managed.

### `trusted` — Accept all connections

```
Default target: ACCEPT
```

All network connections are accepted. Absolutely everything is allowed. This is
the most permissive zone.

**Use when:** Interfaces where you trust everything completely — loopback,
dedicated backup interfaces, or specific high-trust management networks.

> **⚠️  IMPORTANT — Never use `trusted` for internet-facing interfaces**
> The `trusted` zone is appropriate only for interfaces where you genuinely
> control all traffic. Using it for a WAN interface is a critical security
> misconfiguration that allows all inbound connections.

### Zone summary table

| Zone | Target | Masquerade | Default services | Use case |
|------|--------|------------|-----------------|---------|
| `drop` | DROP | No | None | Silent blocklist |
| `block` | REJECT | No | None | Explicit blocklist |
| `public` | default | No | ssh, cockpit, dhcpv6 | Internet-facing servers |
| `external` | default | **Yes** | ssh | Router WAN interface |
| `dmz` | default | No | ssh | DMZ servers |
| `work` | default | No | ssh, ipp, dhcpv6 | Corporate workstations |
| `home` | default | No | ssh, mdns, ipp, samba | Home network |
| `internal` | default | No | ssh, mdns, ipp, samba | Router LAN interface |
| `trusted` | ACCEPT | No | (everything) | Fully trusted segments |

---

↑ [Back to TOC](#table-of-contents)

## 6. Zone Targets

The **target** of a zone defines what happens to packets that do NOT match any
explicit rule within the zone. This is the zone's default verdict.

| Target | Behaviour |
|--------|-----------|
| `default` | Equivalent to REJECT for INPUT; packets are rejected with ICMP |
| `ACCEPT` | All unmatched packets are accepted (`trusted` zone) |
| `DROP` | All unmatched packets are silently discarded (`drop` zone) |
| `REJECT` | All unmatched packets are rejected with ICMP (`block` zone) |

```bash
# Check a zone's target
firewall-cmd --permanent --zone=public --get-target

# Change a zone's target
firewall-cmd --permanent --zone=myzone --set-target=DROP
```

> **💡 What is the difference between `default` and `REJECT`?**
> For the INPUT hook (traffic destined for the host), `default` and `REJECT`
> behave identically — unmatched packets are rejected.
> For the FORWARD hook (traffic being routed through the host), `default`
> means "do not forward unless explicitly allowed" — which is the correct
> behaviour for most zones. `REJECT` would send ICMP errors for all forwarding
> attempts.

---

↑ [Back to TOC](#table-of-contents)

## 7. The Default Zone

The **default zone** is the zone assigned to interfaces that have no explicit
zone binding. On RHEL 10, the default zone is `public`.

```bash
# Get current default zone
firewall-cmd --get-default-zone

# Change default zone (permanent, no reload needed)
firewall-cmd --set-default-zone=internal
```

> **📝 NOTE — Changing the default zone takes effect immediately**
> Unlike most permanent changes, `--set-default-zone` is one of the few
> operations that takes effect without a `--reload`. The daemon updates both
> runtime and permanent state simultaneously.

The default zone matters most when:
- An interface has no explicit zone binding (new interfaces added dynamically)
- NetworkManager is not managing zone assignments
- Container network interfaces are created dynamically

---

↑ [Back to TOC](#table-of-contents)

## 8. Creating and Managing Custom Zones

Predefined zones cover most use cases, but you may need custom zones for:
- Specific security policies not captured by predefined names
- Organisational clarity (e.g., "management" zone, "iot" zone, "guest" zone)
- Different targets or default service sets

### Creating a custom zone

```bash
# Create a new zone (permanent)
firewall-cmd --permanent --new-zone=management

# Add a description (optional but good practice)
# Done by editing the XML file directly or via --set-description

# Set the target
firewall-cmd --permanent --zone=management --set-target=default

# Add services
firewall-cmd --permanent --zone=management --add-service=ssh
firewall-cmd --permanent --zone=management --add-service=cockpit

# Bind a source CIDR (management hosts only)
firewall-cmd --permanent --zone=management --add-source=10.100.0.0/24

# Reload to activate
firewall-cmd --reload

# Verify
firewall-cmd --info-zone=management
```

### Deleting a zone

```bash
# Delete a custom zone (cannot delete predefined zones)
firewall-cmd --permanent --delete-zone=management
firewall-cmd --reload
```

### Listing zones

```bash
# All zone names
firewall-cmd --get-zones

# Active zones only (those with interfaces or sources bound)
firewall-cmd --get-active-zones

# Full config of all zones
firewall-cmd --list-all-zones

# Full config of one zone
firewall-cmd --list-all --zone=public

# Summary info
firewall-cmd --info-zone=internal
```

---

↑ [Back to TOC](#table-of-contents)

## 9. Zone XML Format

Every zone is stored as an XML file. Understanding the format lets you create
zones by editing XML directly — useful for scripting and automation.

### Location

- `/usr/lib/firewalld/zones/` — shipped defaults (read-only)
- `/etc/firewalld/zones/` — custom and overridden zones (read/write)

### Example: `/etc/firewalld/zones/management.xml`

```xml
<?xml version="1.0" encoding="utf-8"?>
<zone target="default">
  <short>Management</short>
  <description>
    Dedicated management network. Allows SSH and Cockpit from
    authorised management workstations only.
  </description>
  <service name="ssh"/>
  <service name="cockpit"/>
  <source address="10.100.0.0/24"/>
</zone>
```

### Full XML schema reference

```xml
<?xml version="1.0" encoding="utf-8"?>
<zone [target="default|ACCEPT|DROP|REJECT"] [version="..."]>
  <short>Human-readable name</short>
  <description>Longer description</description>

  <!-- Interfaces bound to this zone -->
  <interface name="eth0"/>

  <!-- Source CIDRs or IPs bound to this zone -->
  <source address="192.168.1.0/24"/>
  <source address="192.168.2.5"/>
  <source mac="00:11:22:33:44:55"/>  <!-- MAC-based binding -->

  <!-- Allowed services -->
  <service name="ssh"/>
  <service name="http"/>

  <!-- Raw ports -->
  <port protocol="tcp" port="8080"/>
  <port protocol="udp" port="5353"/>

  <!-- Port ranges -->
  <port protocol="tcp" port="6000-6999"/>

  <!-- Protocols (not port-based) -->
  <protocol value="icmp"/>

  <!-- ICMP types to block -->
  <icmp-block name="echo-request"/>

  <!-- Invert ICMP block logic -->
  <icmp-block-inversion/>

  <!-- Enable masquerading -->
  <masquerade/>

  <!-- Forward ports -->
  <forward-port port="80" protocol="tcp" to-port="8080" to-addr="192.168.1.10"/>

  <!-- Rich rules -->
  <rule priority="0">
    <source address="10.0.0.0/8"/>
    <service name="https"/>
    <accept/>
  </rule>

  <!-- Enable intra-zone forwarding -->
  <forward/>
</zone>
```

After editing XML files directly, reload firewalld:

```bash
firewall-cmd --reload
```

---

↑ [Back to TOC](#table-of-contents)

## 10. Intra-zone Forwarding

**Intra-zone forwarding** controls whether traffic between two sources/interfaces
in the *same* zone is automatically forwarded.

On RHEL 10 (firewalld 1.0+), intra-zone forwarding is **enabled by default**
for most zones (indicated by `forward: yes` in `--list-all` output). This means
if two interfaces (or a source CIDR and an interface) are both in the `internal`
zone, traffic between them is automatically forwarded without needing explicit
policies.

```bash
# Check if forward is enabled for a zone
firewall-cmd --list-all --zone=internal
# Look for: forward: yes

# Disable intra-zone forwarding (if you want strict isolation)
firewall-cmd --permanent --zone=internal --remove-forward
firewall-cmd --reload

# Re-enable it
firewall-cmd --permanent --zone=internal --add-forward
firewall-cmd --reload
```

> **📝 NOTE — Forward vs masquerade**
> "Forward" here means *intra-zone* L3 forwarding between interfaces in the
> same zone. It is distinct from masquerading (NAT). You can have forwarding
> enabled without masquerading — traffic is forwarded but source IPs are
> preserved.

---

↑ [Back to TOC](#table-of-contents)

## 11. Zone Inspection Commands

A comprehensive reference for zone-related queries:

```bash
# --- Information ---
firewall-cmd --get-zones                         # All zone names
firewall-cmd --get-active-zones                  # Zones with active bindings
firewall-cmd --get-default-zone                  # Current default zone
firewall-cmd --list-all                          # Default zone full config
firewall-cmd --list-all --zone=internal          # Named zone full config
firewall-cmd --list-all-zones                    # All zones full config
firewall-cmd --info-zone=public                  # Structured zone info
firewall-cmd --permanent --list-all --zone=dmz   # Permanent zone config

# --- Bindings ---
firewall-cmd --zone=internal --list-interfaces   # Interfaces in zone
firewall-cmd --zone=internal --list-sources      # Source bindings in zone
firewall-cmd --get-zone-of-interface=eth0        # Which zone owns this interface
firewall-cmd --get-zone-of-source=10.0.0.5       # Which zone owns this source

# --- Modification ---
firewall-cmd --set-default-zone=public
firewall-cmd --permanent --zone=internal --add-interface=eth1
firewall-cmd --permanent --zone=internal --remove-interface=eth1
firewall-cmd --permanent --zone=trusted --add-source=192.168.100.0/24
firewall-cmd --permanent --zone=trusted --remove-source=192.168.100.0/24
firewall-cmd --permanent --zone=management --change-interface=eth2  # Move interface to zone
firewall-cmd --permanent --new-zone=myzone
firewall-cmd --permanent --delete-zone=myzone
```

---

↑ [Back to TOC](#table-of-contents)

## Lab 3 — Custom Zones and Interface Binding

**Topology:** Two-node (node1 + node2)

**Objective:** Create a custom zone, bind interfaces from the two different lab
networks to different zones on node1, and demonstrate that zone rules are
applied per-interface.

---

### Step 1 — Start the two-node topology

```bash
# 🔧 LAB STEP (on host)
# Start node1 with two interfaces
podman run -d \
  --name node1 --hostname node1 \
  --network labnet-external:ip=172.20.1.10 \
  --cap-add NET_ADMIN --cap-add SYS_ADMIN --cap-add NET_RAW \
  --security-opt label=disable \
  --tmpfs /tmp --tmpfs /run --tmpfs /run/lock \
  -v /sys/fs/cgroup:/sys/fs/cgroup:ro \
  firewalld-lab

podman network connect --ip 172.20.2.10 labnet-dmz node1

# Start node2 (DMZ server)
podman run -d \
  --name node2 --hostname node2 \
  --network labnet-dmz:ip=172.20.2.20 \
  --cap-add NET_ADMIN --cap-add SYS_ADMIN --cap-add NET_RAW \
  --security-opt label=disable \
  --tmpfs /tmp --tmpfs /run --tmpfs /run/lock \
  -v /sys/fs/cgroup:/sys/fs/cgroup:ro \
  firewalld-lab

sleep 5
```

---

### Step 2 — Observe the initial zone state on node1

```bash
# 🔧 LAB STEP (inside node1)
podman exec -it node1 bash

# What interfaces exist?
ip link show

# Which zones are active?
firewall-cmd --get-active-zones
```

> **💡 CONCEPT CHECK**
> You should see both `eth0` (172.20.1.10) and `eth1` (172.20.2.10) listed.
> Both may be in the `public` zone (the default). We will change this.

---

### Step 3 — Assign interfaces to appropriate zones

```bash
# 🔧 LAB STEP (inside node1)

# eth0 faces the external network — keep it in public
# eth1 faces the DMZ — put it in dmz zone

# First, remove eth1 from public (if it was assigned there)
firewall-cmd --permanent --zone=public --remove-interface=eth1 2>/dev/null || true

# Assign eth1 to the dmz zone
firewall-cmd --permanent --zone=dmz --add-interface=eth1

# Reload to activate
firewall-cmd --reload

# Verify
firewall-cmd --get-active-zones
```

Expected output:
```
dmz
  interfaces: eth1
public
  interfaces: eth0
```

---

### Step 4 — Create a custom "webservers" zone

```bash
# 🔧 LAB STEP (inside node1)

# Create the zone
firewall-cmd --permanent --new-zone=webservers

# Add allowed services (HTTP only — no SSH)
firewall-cmd --permanent --zone=webservers --add-service=http
firewall-cmd --permanent --zone=webservers --add-service=https

# Bind the source CIDR of the DMZ to this zone
# (all traffic FROM the DMZ is treated as coming from web servers)
firewall-cmd --permanent --zone=webservers --add-source=172.20.2.0/24

# Reload
firewall-cmd --reload

# Verify
firewall-cmd --info-zone=webservers
```

---

### Step 5 — Test zone rule enforcement

```bash
# 🔧 LAB STEP (inside node2)
podman exec -it node2 bash

# From node2 (172.20.2.20), try to reach node1 on various ports

# HTTP — should be allowed (webservers zone allows http)
nc -zv 172.20.2.10 80
# Expected: Connection to 172.20.2.10 80 port [tcp/http] succeeded!

# HTTPS — should be allowed
nc -zv 172.20.2.10 443

# SSH — should be REJECTED (webservers zone doesn't allow ssh)
nc -zv -w2 172.20.2.10 22
# Expected: nc: connect to 172.20.2.10 port 22 (tcp) failed: Connection refused
# (reject sends an ICMP error, so this fails immediately, not timeout)
```

> **💡 CONCEPT CHECK**
> Traffic from 172.20.2.20 matched the source binding `172.20.2.0/24 → webservers`
> zone. The source binding took precedence over the interface binding (eth1 →
> dmz zone). This demonstrates the source-over-interface precedence rule.

---

### Step 6 — Verify zone selection in nftables

```bash
# 🔧 LAB STEP (inside node1)

# See the zone dispatch chain
nft list chain inet firewalld filter_IN_ZONES

# You should see rules like:
# ip saddr 172.20.2.0/24 goto filter_IN_webservers
# iifname "eth0" goto filter_IN_public
# iifname "eth1" goto filter_IN_dmz
```

---

### Step 7 — Look at the XML that was created

```bash
# 🔧 LAB STEP (inside node1)
cat /etc/firewalld/zones/webservers.xml
```

---

### Step 8 — Clean up

```bash
# 🔧 LAB STEP (inside node1)
firewall-cmd --permanent --delete-zone=webservers
firewall-cmd --permanent --zone=public --add-interface=eth1
firewall-cmd --permanent --zone=dmz --remove-interface=eth1
firewall-cmd --reload
firewall-cmd --get-active-zones
```

```bash
# On host — stop containers
podman stop node1 node2
```

---

### Summary

You learned:

1. Zones are named trust levels — the label expresses *intent*, the rules express *policy*
2. Traffic is assigned to zones by source binding (first) or interface binding (fallback)
3. Source bindings take precedence over interface bindings
4. You can create custom zones with custom rules, targets, and bindings
5. The nftables zone dispatch chain shows exactly how firewalld implements zone selection

---

*Module 03 complete.*

**Continue to [Module 04 — Services, Ports, and Protocols →](./04-services-ports-and-protocols.md)**

---

© 2026 Jaco Steyn — Licensed under CC BY-SA 4.0

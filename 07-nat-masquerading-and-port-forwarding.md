# Module 07 — NAT, Masquerading, and Port Forwarding
[![CC BY-NC-SA 4.0](https://img.shields.io/badge/License-CC%20BY--NC--SA%204.0-lightgrey)](./LICENSE.md)
[![RHEL 10](https://img.shields.io/badge/platform-RHEL%2010-red)](https://access.redhat.com/products/red-hat-enterprise-linux)
[![firewalld](https://img.shields.io/badge/firewalld-RHEL%2010-orange)](https://access.redhat.com/products/red-hat-enterprise-linux)

> **Goal:** Build routers, gateways, and reverse proxies with firewalld. Understand
> SNAT (masquerading) and DNAT (port forwarding) at a kernel level, configure
> them via firewall-cmd, and understand the StrictForwardPorts option that
> controls how container-published ports interact with your NAT configuration.

---

## Table of Contents

1. [1. NAT Fundamentals](#1-nat-fundamentals)
2. [2. IP Forwarding — The Kernel Prerequisite](#2-ip-forwarding-the-kernel-prerequisite)
3. [3. Masquerading (SNAT)](#3-masquerading-snat)
4. [4. Port Forwarding (DNAT)](#4-port-forwarding-dnat)
5. [5. StrictForwardPorts](#5-strictforwardports)
6. [6. Port Forwarding in Policies vs Zones](#6-port-forwarding-in-policies-vs-zones)
7. [7. NAT and IPv6](#7-nat-and-ipv6)
8. [8. How NAT Appears in nftables](#8-how-nat-appears-in-nftables)
9. [9. Building a Gateway Scenario](#9-building-a-gateway-scenario)
10. [Lab 7 — Gateway Container with Masquerade](#lab-7-gateway-container-with-masquerade)

---

↑ [Back to TOC](#table-of-contents)

## 1. NAT Fundamentals

**Network Address Translation (NAT)** modifies IP packet headers as they pass
through a router or gateway. There are two primary types:

### SNAT — Source NAT (Masquerading)

Rewrites the **source address** of packets as they leave a network. Used when
many internal hosts share a single external IP address (the classic home router
scenario).

```
Internal host (10.0.0.5:49234) ──sends packet──► Gateway (10.0.0.1/203.0.113.1)
                                                    │
                                                    │ Source NAT: 10.0.0.5 → 203.0.113.1
                                                    │
                                                    ▼
                                                Internet server (198.51.100.1:80)
                                                sees: source=203.0.113.1:49234
```

When the reply comes back (destination=203.0.113.1:49234), the gateway uses
its NAT table to translate back: destination → 10.0.0.5:49234.

**Masquerading** is a special form of SNAT where the source address is
automatically set to the outgoing interface's IP address — useful when the
interface has a dynamic IP (DHCP).

### DNAT — Destination NAT (Port Forwarding)

Rewrites the **destination address** of incoming packets. Used to redirect
external traffic to an internal host.

```
Internet client (1.2.3.4:12345) ──► Gateway (203.0.113.1:80)
                                        │
                                        │ Destination NAT: 203.0.113.1:80 → 10.0.0.100:8080
                                        │
                                        ▼
                                    Internal web server (10.0.0.100:8080)
```

The internal server never sees the original destination (203.0.113.1) — it
sees 10.0.0.100:8080 as the destination. The gateway maintains the mapping
to translate replies back.

---

↑ [Back to TOC](#table-of-contents)

## 2. IP Forwarding — The Kernel Prerequisite

For a Linux host to act as a router/gateway, the kernel must be configured to
forward packets between interfaces. By default, Linux does NOT forward packets.

### Enabling IP forwarding

```bash
# Check current state
sysctl net.ipv4.ip_forward
sysctl net.ipv6.conf.all.forwarding

# Enable IPv4 forwarding (runtime — lost on reboot)
sysctl -w net.ipv4.ip_forward=1

# Enable IPv6 forwarding
sysctl -w net.ipv6.conf.all.forwarding=1

# Make persistent (survives reboot)
cat > /etc/sysctl.d/99-forwarding.conf << 'EOF'
net.ipv4.ip_forward = 1
net.ipv6.conf.all.forwarding = 1
EOF
sysctl --system  # Apply without reboot
```

> **📝 NOTE — firewalld and IP forwarding**
> When you enable masquerading or add forward-port rules, firewalld does NOT
> automatically enable IP forwarding at the kernel level. You must enable it
> separately. This is by design — firewalld manages the firewall; kernel
> parameters are outside its scope.
>
> Exception: Some older firewalld versions would write sysctl settings. On
> RHEL 10, always set IP forwarding explicitly.

---

↑ [Back to TOC](#table-of-contents)

## 3. Masquerading (SNAT)

### Enabling masquerading on a zone

```bash
# Enable masquerade on the external zone (appropriate for WAN interface)
firewall-cmd --permanent --zone=external --add-masquerade

# Verify
firewall-cmd --zone=external --query-masquerade

# Remove masquerade
firewall-cmd --permanent --zone=external --remove-masquerade
```

> **📝 NOTE — external zone has masquerade enabled by default**
> The `external` predefined zone ships with masquerade already enabled. You
> only need to explicitly add masquerade if you're using a custom zone or a
> different predefined zone for your WAN interface.

### Masquerade on a policy (preferred for RHEL 10)

```bash
# Better approach: masquerade in a policy for explicit direction control
firewall-cmd --permanent --new-policy int_to_ext
firewall-cmd --permanent --policy int_to_ext --add-ingress-zone internal
firewall-cmd --permanent --policy int_to_ext --add-egress-zone external
firewall-cmd --permanent --policy int_to_ext --set-target ACCEPT
firewall-cmd --permanent --policy int_to_ext --add-masquerade
firewall-cmd --reload

# Verify
firewall-cmd --policy int_to_ext --query-masquerade
```

### How masquerade works with conntrack

When a masqueraded packet leaves the gateway:
1. The kernel records the original source IP:port in the conntrack table
2. The source IP is rewritten to the outgoing interface IP
3. When the reply arrives, conntrack finds the original mapping
4. The destination IP is rewritten back to the original internal host
5. The packet is forwarded to the internal host

This entire process is transparent to both the internal host and the external
server. The conntrack table entry expires after the connection closes.

---

↑ [Back to TOC](#table-of-contents)

## 4. Port Forwarding (DNAT)

### Basic syntax

```bash
firewall-cmd --permanent --zone=external \
  --add-forward-port=port=80:proto=tcp:toport=8080:toaddr=192.168.1.100
```

Breaking down the syntax:
- `port=80` — external port to listen on
- `proto=tcp` — protocol (tcp or udp)
- `toport=8080` — destination port on the target host
- `toaddr=192.168.1.100` — destination host IP (omit for local redirect)

### Types of port forwarding

**Type 1: Redirect to different port on SAME host**

```bash
# Redirect local port 80 to local port 8080 (e.g., rootless process can't bind 80)
firewall-cmd --permanent --zone=public \
  --add-forward-port=port=80:proto=tcp:toport=8080
# Note: no toaddr = redirect to localhost
```

**Type 2: Forward to a different internal host**

```bash
# Forward TCP port 22 on this gateway to a jump host inside
firewall-cmd --permanent --zone=external \
  --add-forward-port=port=2222:proto=tcp:toport=22:toaddr=192.168.1.50
```

**Type 3: Forward to a different internal host AND different port**

```bash
# Incoming :443 → internal HTTPS server on :8443
firewall-cmd --permanent --zone=external \
  --add-forward-port=port=443:proto=tcp:toport=8443:toaddr=192.168.1.100
```

**Type 4: Forward a port range**

```bash
# Forward incoming 5000-5010 to same ports on internal host
firewall-cmd --permanent --zone=external \
  --add-forward-port=port=5000-5010:proto=tcp:toport=5000-5010:toaddr=192.168.1.100
```

### Listing and removing forward ports

```bash
# List
firewall-cmd --zone=external --list-forward-ports

# Remove (exact string match required)
firewall-cmd --permanent --zone=external \
  --remove-forward-port=port=80:proto=tcp:toport=8080:toaddr=192.168.1.100
```

### Port forwarding and hairpin NAT

When an internal host tries to reach an external IP that's forwarded back to
an internal host, this is called **hairpin NAT** (or NAT loopback). It requires
masquerade to be enabled on the internal zone for the reply to reach the
originator correctly.

This is a common source of confusion: "port forwarding works from outside but
not from inside." If this happens, enable masquerade on the internal zone or
policy.

---

↑ [Back to TOC](#table-of-contents)

## 5. StrictForwardPorts

`StrictForwardPorts` is a RHEL 10 / firewalld 2.x configuration option in
`/etc/firewalld/firewalld.conf` that controls how container-published ports
interact with firewalld's forwarding rules.

### The problem it solves

When Podman or Docker publishes a container port (`-p 8080:80`), the container
runtime creates NAT rules in nftables (or iptables). These rules allow external
traffic to reach the container regardless of what firewalld says.

Without `StrictForwardPorts`, a container with `-p 8080:80` is accessible
even if firewalld has no rule allowing port 8080. The container runtime's rules
bypass firewalld's zone policies.

### `StrictForwardPorts=no` (default)

Container-published ports work seamlessly. The container runtime adds DNAT
rules and firewalld allows the forwarded traffic implicitly. This is convenient
and is the default.

```
External client → port 8080 → firewalld zone rule (8080 not allowed)
                                     ↓ BUT
                            Container runtime DNAT rule → container:80
                            (bypasses firewalld zone check)
```

### `StrictForwardPorts=yes` (strict mode)

firewalld checks all forwarded traffic against its own forward-port rules.
Container-published ports are NOT automatically allowed. You must explicitly
add a forward-port rule for each published container port.

```
External client → port 8080 → firewalld zone rule (8080 not allowed)
                                     ↓
                              BLOCKED — no firewalld forward-port rule exists
                              (container runtime's DNAT rule is ignored)
```

### Enabling strict mode

```bash
# Edit /etc/firewalld/firewalld.conf
sed -i 's/^StrictForwardPorts=.*/StrictForwardPorts=yes/' /etc/firewalld/firewalld.conf

# Reload
firewall-cmd --reload

# Now explicitly add forward-port rules for containers
firewall-cmd --permanent --zone=public \
  --add-forward-port=port=8080:proto=tcp:toport=80:toaddr=172.17.0.2
firewall-cmd --reload
```

Module 08 covers the full container integration story including how to use
strict mode effectively.

---

↑ [Back to TOC](#table-of-contents)

## 6. Port Forwarding in Policies vs Zones

Port forwarding can be configured in both zones and policies. The choice
affects which traffic is subject to the DNAT rule:

### Zone forward-port

Applied to traffic arriving on interfaces/sources in that zone:

```bash
# All traffic arriving in the external zone on port 80 is forwarded
firewall-cmd --permanent --zone=external \
  --add-forward-port=port=80:proto=tcp:toport=8080:toaddr=172.20.2.20
```

### Policy forward-port

Applied to traffic flowing between specific zones:

```bash
# Only traffic from public zone going to HOST is forwarded
firewall-cmd --permanent --new-policy port_fwd
firewall-cmd --permanent --policy port_fwd \
  --add-ingress-zone public \
  --add-egress-zone HOST
firewall-cmd --permanent --policy port_fwd \
  --add-forward-port port=80:proto=tcp:toport=8080:toaddr=172.20.2.20
firewall-cmd --reload
```

Policies are more precise — use them when you want forwarding to apply only
for specific zone-to-zone traffic flows.

---

↑ [Back to TOC](#table-of-contents)

## 7. NAT and IPv6

Masquerading (SNAT) is fundamentally an IPv4 concept. IPv6 was designed for
end-to-end addressing — every device gets a globally routable address, so NAT
is theoretically unnecessary.

In practice:
- Simple `--add-masquerade` only applies to IPv4
- IPv6 typically uses NPTv6 (Network Prefix Translation) for prefix matching
  — different concept, not supported by firewalld's masquerade command
- Most gateway setups should use IPv4 masquerade and native IPv6 routing

If you need IPv6 NAT (unusual), use a rich rule with a mark and a raw nftables
postrouting rule (Module 12).

---

↑ [Back to TOC](#table-of-contents)

## 8. How NAT Appears in nftables

Understanding how firewalld implements NAT in nftables is essential for
troubleshooting.

### SNAT (masquerade)

```bash
# After enabling masquerade on external zone, inspect nftables
nft list table ip firewalld
# Look for the nat chain
```

The masquerade rule appears in the `postrouting` chain:

```
chain nat_POST_external {
  masquerade
}
```

### DNAT (port forwarding)

```bash
nft list table ip firewalld
# Look for the prerouting chain
```

Port forwarding appears in the `prerouting` chain:

```
chain nat_PRE_external {
  tcp dport 80 dnat to 172.20.2.20:8080
}
```

### Viewing the full NAT table

```bash
# IPv4 NAT rules
nft list table ip firewalld

# Count NAT rules
nft list table ip firewalld | grep -c "dnat\|masquerade"
```

---

↑ [Back to TOC](#table-of-contents)

## 9. Building a Gateway Scenario

A complete gateway configuration:

```bash
# 1. Enable IP forwarding
sysctl -w net.ipv4.ip_forward=1

# 2. Assign interfaces to zones
firewall-cmd --permanent --zone=external --add-interface=eth0  # WAN
firewall-cmd --permanent --zone=internal --add-interface=eth1  # LAN

# 3. Use the gateway Policy Set (easiest approach on RHEL 10)
firewall-cmd --permanent --policy-set gateway --remove-disable
firewall-cmd --reload

# --- OR do it manually ---

# 3a. Allow outbound traffic with masquerade
firewall-cmd --permanent --new-policy lan_to_wan
firewall-cmd --permanent --policy lan_to_wan --add-ingress-zone internal
firewall-cmd --permanent --policy lan_to_wan --add-egress-zone external
firewall-cmd --permanent --policy lan_to_wan --set-target ACCEPT
firewall-cmd --permanent --policy lan_to_wan --add-masquerade

# 3b. Block unsolicited inbound (default for external zone)
# external zone already has target=default which blocks unlisted traffic

# 3c. Add port forwarding for services
firewall-cmd --permanent --zone=external \
  --add-forward-port=port=80:proto=tcp:toport=80:toaddr=192.168.1.100

firewall-cmd --reload
```

---

↑ [Back to TOC](#table-of-contents)

## Lab 7 — Gateway Container with Masquerade

**Topology:** Two-node (node1=gateway, node2=internal client/server)

**Objective:** Configure node1 as a NAT gateway. node2 (internal) will use
node1 to reach the external network. Then add port forwarding so external
traffic can reach node2.

---

### Step 1 — Start two-node topology

```bash
# 🔧 LAB STEP (on host)
podman run -d --name node1 --hostname node1 \
  --network labnet-external:ip=172.20.1.10 \
  --cap-add NET_ADMIN --cap-add SYS_ADMIN --cap-add NET_RAW \
  --security-opt label=disable \
  --tmpfs /tmp --tmpfs /run --tmpfs /run/lock \
  -v /sys/fs/cgroup:/sys/fs/cgroup:ro firewalld-lab

podman network connect --ip 172.20.2.10 labnet-dmz node1

podman run -d --name node2 --hostname node2 \
  --network labnet-dmz:ip=172.20.2.20 \
  --cap-add NET_ADMIN --cap-add SYS_ADMIN --cap-add NET_RAW \
  --security-opt label=disable \
  --tmpfs /tmp --tmpfs /run --tmpfs /run/lock \
  -v /sys/fs/cgroup:/sys/fs/cgroup:ro firewalld-lab

sleep 5
```

---

### Step 2 — Configure node1 as a gateway

```bash
# 🔧 LAB STEP (inside node1)
podman exec -it node1 bash

# Enable IP forwarding
sysctl -w net.ipv4.ip_forward=1

# Assign zones
firewall-cmd --permanent --zone=external --add-interface=eth0
firewall-cmd --permanent --zone=internal --add-interface=eth1
firewall-cmd --permanent --zone=public --remove-interface=eth0 2>/dev/null || true
firewall-cmd --permanent --zone=public --remove-interface=eth1 2>/dev/null || true

# Create outbound masquerade policy
firewall-cmd --permanent --new-policy int_to_ext
firewall-cmd --permanent --policy int_to_ext --add-ingress-zone internal
firewall-cmd --permanent --policy int_to_ext --add-egress-zone external
firewall-cmd --permanent --policy int_to_ext --set-target ACCEPT
firewall-cmd --permanent --policy int_to_ext --add-masquerade

firewall-cmd --reload
firewall-cmd --get-active-zones
```

---

### Step 3 — Configure node2 to use node1 as gateway

```bash
# 🔧 LAB STEP (inside node2)
podman exec -it node2 bash

# Set default route via node1's internal interface
ip route add default via 172.20.2.10

# Verify
ip route show
```

---

### Step 4 — Test outbound connectivity from node2

```bash
# 🔧 LAB STEP (inside node2)
# Try to reach the host's external network through node1
ping -c 2 172.20.1.1  # Gateway of external network
# Should succeed — traffic is masqueraded through node1
```

---

### Step 5 — Start a web server on node2

```bash
# 🔧 LAB STEP (inside node2)
python3 -m http.server 80 &
firewall-cmd --zone=public --add-service=http
```

---

### Step 6 — Add port forwarding on node1

```bash
# 🔧 LAB STEP (inside node1)

# Forward incoming port 8080 on external interface → node2:80
firewall-cmd --permanent --zone=external \
  --add-forward-port=port=8080:proto=tcp:toport=80:toaddr=172.20.2.20

# Also need to allow port 8080 on the external zone
firewall-cmd --permanent --zone=external --add-port=8080/tcp

firewall-cmd --reload

# Verify
firewall-cmd --zone=external --list-forward-ports
firewall-cmd --zone=external --list-ports
```

---

### Step 7 — Test port forwarding from the host

```bash
# 🔧 LAB STEP (on host)
# Connect to node1:8080 — should be forwarded to node2:80
curl -m 5 http://172.20.1.10:8080/
# Should return node2's web server response
```

---

### Step 8 — Inspect the nftables NAT rules

```bash
# 🔧 LAB STEP (inside node1)
# See the full NAT table
nft list table ip firewalld

# Find the masquerade rule
nft list table ip firewalld | grep masquerade

# Find the DNAT rule
nft list table ip firewalld | grep dnat
```

---

### Step 9 — Clean up

```bash
# 🔧 LAB STEP (inside node1)
firewall-cmd --permanent --delete-policy int_to_ext 2>/dev/null || true
firewall-cmd --permanent --zone=external --remove-forward-port=port=8080:proto=tcp:toport=80:toaddr=172.20.2.20
firewall-cmd --permanent --zone=external --remove-port=8080/tcp
firewall-cmd --reload
```

```bash
# On host
podman stop node1 node2
```

---

### Summary

| Concept | Command |
|---------|---------|
| Enable masquerade on zone | `--add-masquerade` on `external` zone |
| Enable masquerade in policy | `--add-masquerade` on policy with ingress/egress zones |
| Forward external port to internal host | `--add-forward-port=port=N:proto=tcp:toport=M:toaddr=IP` |
| Check IP forwarding | `sysctl net.ipv4.ip_forward` |
| View NAT rules in nftables | `nft list table ip firewalld` |
| Strict container port control | `StrictForwardPorts=yes` in `firewalld.conf` |

---

*Module 07 complete.*

**Continue to [Module 08 — Container Integration →](./08-container-integration.md)**

---

© 2026 UncleJS — Licensed under CC BY-NC-SA 4.0

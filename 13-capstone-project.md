# Module 13 — Capstone Project: Production Firewall for a Three-Tier Application
[![CC BY-NC-SA 4.0](https://img.shields.io/badge/License-CC%20BY--NC--SA%204.0-lightgrey)](./LICENSE.md)
[![RHEL 10](https://img.shields.io/badge/platform-RHEL%2010-red)](https://access.redhat.com/products/red-hat-enterprise-linux)
[![firewalld](https://img.shields.io/badge/firewalld-RHEL%2010-orange)](https://access.redhat.com/products/red-hat-enterprise-linux)

## Table of Contents

1. [Overview](#overview)
2. [The Scenario](#the-scenario)
3. [Part 1 — Design (No Commands Yet)](#part-1-design-no-commands-yet)
4. [Part 2 — Node 1 (Gateway) Configuration](#part-2-node-1-gateway-configuration)
5. [Part 3 — Node 2 (Web/App Server) Configuration](#part-3-node-2-webapp-server-configuration)
6. [Part 4 — Node 3 (Database Server) Configuration](#part-4-node-3-database-server-configuration)
7. [Part 5 — Auditd Configuration (All Nodes)](#part-5-auditd-configuration-all-nodes)
8. [Part 6 — Verification Tests](#part-6-verification-tests)
9. [Part 7 — Hardening Review Checklist](#part-7-hardening-review-checklist)
10. [Part 8 — nftables Deep-Dive Verification](#part-8-nftables-deep-dive-verification)
11. [Part 9 — Bonus Challenges](#part-9-bonus-challenges)
12. [Part 10 — Capstone Teardown](#part-10-capstone-teardown)
13. [Capstone Completion Criteria](#capstone-completion-criteria)
14. [Skills Demonstrated](#skills-demonstrated)

---

↑ [Back to TOC](#table-of-contents)

## Overview

This capstone project integrates everything from the course into a single, end-to-end deployment. You will design, implement, verify, and harden a complete firewall configuration for a three-tier web application using the lab nodes as production-equivalent hosts.

**Estimated time**: 3–5 hours  
**Difficulty**: Expert

---

↑ [Back to TOC](#table-of-contents)

## The Scenario

Your company is deploying a three-tier web application on bare-metal (modeled by your Podman lab nodes):

```
Internet / External Users
         │
    [node1] — Gateway/Load Balancer
         │            │
   [eth0]             [eth1 + eth2]
 External           DMZ     Internal
172.20.1.0/24   172.20.2.0/24  172.20.3.0/24
                    │               │
                [node2]         [node3]
              Web/App Server   Database Server
```

### Application architecture

| Tier | Host | Services | Allowed clients |
|------|------|----------|----------------|
| Gateway | node1 | HTTPS (443), HTTP→HTTPS redirect (80), SSH admin (22) | Internet (443/80), Management subnet only (22) |
| Web/App | node2 | HTTP (8080), SSH admin (22) | node1 internal IP only (8080), Management subnet (22) |
| Database | node3 | PostgreSQL (5432), SSH admin (22) | node2 IP only (5432), Management subnet (22) |

### Management subnet
`172.20.3.30` (node3's IP — use node3 as the management host for testing)

### Security requirements
1. Internet → node1: only TCP 80 and 443; all else DROP (no ICMP from internet)
2. node1 → node2: only TCP 8080 and ICMP for health checks
3. node2 → node3: only TCP 5432
4. Management host → all nodes: SSH (22) + ICMP
5. All outbound allowed from all nodes (for package updates etc.)
6. Logging: all denied packets must be logged
7. Rate limiting: max 50 new HTTP(S) connections/second per source IP; violators blocked 10 minutes
8. NAT: node1 masquerades for DMZ and Internal networks going to internet
9. Lockdown: enabled on all nodes; only root and NetworkManager whitelisted
10. nftables audit: all config changes logged to auditd

---

↑ [Back to TOC](#table-of-contents)

## Part 1 — Design (No Commands Yet)

Before writing a single `firewall-cmd`, document your design.

### 1.1 — Zone assignment

Fill in this table with your planned zone-to-interface mappings:

| Node | Interface | Network | Planned Zone | Reasoning |
|------|-----------|---------|-------------|-----------|
| node1 | eth0 | 172.20.1.0/24 | `external` | Internet-facing; DROP target |
| node1 | eth1 | 172.20.2.0/24 | `dmz` | Semi-trusted DMZ servers |
| node1 | eth2 | 172.20.3.0/24 | `internal` | Trusted internal network |
| node2 | eth0 | 172.20.2.0/24 | `dmz` | Receives traffic from gateway |
| node3 | eth0 | 172.20.3.0/24 | `internal` | Isolated database tier |

### 1.2 — Policy requirements mapping

| Requirement | firewalld mechanism | Module reference |
|-------------|--------------------|-----------------:|
| Internet → node1 (443/80 only) | `external` zone services | Module 04 |
| Block all else at node1 external | Zone target=DROP + LogDenied | Modules 03, 10 |
| node1 → node2 (8080 + ICMP) | `dmz` zone policy or rich rule | Modules 05, 06 |
| node2 → node3 (5432 only) | `internal` zone service | Module 04 |
| Management SSH/ICMP everywhere | Source-based zone + service | Module 03 |
| NAT / masquerade | external zone masquerade | Module 07 |
| Rate limiting | Custom nftables meter | Module 12 |
| Lockdown | lockdown-on + whitelist | Module 11 |
| Logging denied | LogDenied=all | Module 10 |
| Audit | auditctl on /etc/firewalld | Module 11 |

---

↑ [Back to TOC](#table-of-contents)

## Part 2 — Node 1 (Gateway) Configuration

### Step 2.1 — Verify lab is running and nodes are reachable

```bash
~/firewalld-lab/start-lab.sh

podman exec node1 firewall-cmd --state
podman exec node2 firewall-cmd --state
podman exec node3 firewall-cmd --state
# All should return: running
```

### Step 2.2 — Assign interfaces to zones on node1

```bash
podman exec -it node1 bash

# Check current interface assignments
firewall-cmd --get-active-zones
ip addr show

# Assign interfaces (adjust eth names to match your container)
# eth0 → external (internet-facing)
firewall-cmd --zone=external --add-interface=eth0 --permanent

# eth1 → dmz
firewall-cmd --zone=dmz --add-interface=eth1 --permanent

# eth2 → internal
firewall-cmd --zone=internal --add-interface=eth2 --permanent

firewall-cmd --reload
firewall-cmd --get-active-zones
```

### Step 2.3 — Configure the external zone

```bash
# Set target to DROP — silently drop all unmatched external traffic
firewall-cmd --zone=external --set-target=DROP --permanent

# Allow only HTTP and HTTPS from internet
firewall-cmd --zone=external --add-service=http --permanent
firewall-cmd --zone=external --add-service=https --permanent

# Block ICMP from internet (no ping responses to external)
firewall-cmd --zone=external --add-icmp-block=echo-request --permanent
firewall-cmd --zone=external --add-icmp-block=echo-reply --permanent

# Remove SSH from external (management is via internal only)
firewall-cmd --zone=external --remove-service=ssh --permanent 2>/dev/null || true

# Enable masquerade (NAT for outbound traffic from DMZ/Internal)
firewall-cmd --zone=external --add-masquerade --permanent

# Enable logging for denied packets
firewall-cmd --set-log-denied=all

firewall-cmd --reload

# Verify
firewall-cmd --zone=external --list-all
```

### Step 2.4 — Configure the DMZ zone on node1 (toward node2)

```bash
# DMZ zone: allow node1 to forward HTTP to node2 and receive health check ICMP
# The DMZ zone on node1's eth1 governs traffic between node1 and node2

# Allow HTTP from internal/external (forwarded)
firewall-cmd --zone=dmz --add-service=http --permanent

# Allow ICMP for health checks
firewall-cmd --zone=dmz --add-protocol=icmp --permanent

# Remove SSH from DMZ zone (SSH to node2 is from management only)
firewall-cmd --zone=dmz --remove-service=ssh --permanent 2>/dev/null || true

firewall-cmd --reload
firewall-cmd --zone=dmz --list-all
```

### Step 2.5 — Configure the internal zone on node1 (toward node3)

```bash
# Internal zone: allow management SSH/ICMP; PostgreSQL not needed on node1 itself
firewall-cmd --zone=internal --add-service=ssh --permanent
firewall-cmd --zone=internal --add-protocol=icmp --permanent

# Add management host as trusted source for SSH
firewall-cmd --zone=internal --add-source=172.20.3.30 --permanent

firewall-cmd --reload
firewall-cmd --zone=internal --list-all
```

### Step 2.6 — Port forwarding: HTTPS on node1 → HTTP on node2

```bash
# Forward external HTTPS (443) to node2:8080
# Use a pre-routing DNAT rule
firewall-cmd --zone=external --add-forward-port=\
port=443:proto=tcp:toport=8080:toaddr=172.20.2.20 --permanent

# Forward HTTP (80) → redirect to HTTPS (handled at app level, but model it here)
firewall-cmd --zone=external --add-forward-port=\
port=80:proto=tcp:toport=8080:toaddr=172.20.2.20 --permanent

firewall-cmd --reload
```

### Step 2.7 — Set up inter-zone policy (node1 as router)

```bash
# Policy: allow forwarding from external → dmz (for the port forwards to work)
firewall-cmd --new-policy=ext-to-dmz --permanent
firewall-cmd --policy=ext-to-dmz --add-ingress-zone=external --permanent
firewall-cmd --policy=ext-to-dmz --add-egress-zone=dmz --permanent
firewall-cmd --policy=ext-to-dmz --set-target=ACCEPT --permanent

# Policy: allow forwarding dmz → external (for outbound traffic from node2)
firewall-cmd --new-policy=dmz-to-ext --permanent
firewall-cmd --policy=dmz-to-ext --add-ingress-zone=dmz --permanent
firewall-cmd --policy=dmz-to-ext --add-egress-zone=external --permanent
firewall-cmd --policy=dmz-to-ext --set-target=ACCEPT --permanent

# Policy: internal → external for package updates
firewall-cmd --new-policy=int-to-ext --permanent
firewall-cmd --policy=int-to-ext --add-ingress-zone=internal --permanent
firewall-cmd --policy=int-to-ext --add-egress-zone=external --permanent
firewall-cmd --policy=int-to-ext --set-target=ACCEPT --permanent

firewall-cmd --reload
firewall-cmd --list-all-policies
```

### Step 2.8 — Rate limiting with custom nftables (on node1)

```bash
# Create rate-limiting table for internet-facing port 80/443
cat > /etc/nftables.d/ratelimit.nft << 'EOF'
table inet http_guard {

    set burst_blocked {
        type ipv4_addr
        flags dynamic, timeout
        timeout 10m
        comment "IPs auto-blocked for exceeding rate limit"
    }

    chain input_http_guard {
        type filter hook input priority -2;

        # Established connections skip rate check
        ct state established,related accept

        # Drop already-blocked sources immediately
        ip saddr @burst_blocked drop

        # Rate limit new HTTP/HTTPS connections
        tcp dport { 80, 443 } ct state new \
            meter http_rate { ip saddr limit rate over 50/second burst 100 packets } \
            add @burst_blocked { ip saddr } \
            drop
    }
}
EOF

nft -f /etc/nftables.d/ratelimit.nft
nft list table inet http_guard
```

### Step 2.9 — Lockdown on node1

```bash
# Write whitelist
cat > /etc/firewalld/lockdown-whitelist.xml << 'EOF'
<?xml version="1.0" encoding="utf-8"?>
<whitelist>
  <command name="/usr/bin/python3 -s /usr/bin/firewall-cmd*"/>
  <selinux context="system_u:system_r:NetworkManager_t:s0"/>
  <user id="0"/>
</whitelist>
EOF

# Enable lockdown
sed -i 's/^#*Lockdown=.*/Lockdown=yes/' /etc/firewalld/firewalld.conf
grep -q "^Lockdown=" /etc/firewalld/firewalld.conf || echo "Lockdown=yes" >> /etc/firewalld/firewalld.conf

firewall-cmd --reload
firewall-cmd --query-lockdown   # → yes
```

---

↑ [Back to TOC](#table-of-contents)

## Part 3 — Node 2 (Web/App Server) Configuration

```bash
podman exec -it node2 bash
```

### Step 3.1 — Zone assignment

```bash
# node2 sits in the DMZ — eth0 faces the DMZ network
firewall-cmd --zone=dmz --add-interface=eth0 --permanent
firewall-cmd --reload
```

### Step 3.2 — DMZ zone: allow only port 8080 from node1

```bash
# Remove default services from dmz zone
firewall-cmd --zone=dmz --remove-service=ssh --permanent 2>/dev/null || true
firewall-cmd --zone=dmz --remove-service=http --permanent 2>/dev/null || true

# Allow port 8080 only from node1's DMZ IP (172.20.2.10 — node1's eth1)
firewall-cmd --zone=dmz --add-rich-rule='
  rule family="ipv4"
  source address="172.20.2.10"
  port port="8080" protocol="tcp"
  accept' --permanent

# Allow ICMP from node1 (health checks)
firewall-cmd --zone=dmz --add-rich-rule='
  rule family="ipv4"
  source address="172.20.2.10"
  protocol value="icmp"
  accept' --permanent

# Allow SSH from management host only
firewall-cmd --zone=dmz --add-rich-rule='
  rule family="ipv4"
  source address="172.20.3.30"
  service name="ssh"
  accept' --permanent

# Set target to DROP for all else
firewall-cmd --zone=dmz --set-target=DROP --permanent

# Enable logging
firewall-cmd --set-log-denied=all

firewall-cmd --reload
firewall-cmd --zone=dmz --list-all
```

### Step 3.3 — Lockdown on node2

```bash
cat > /etc/firewalld/lockdown-whitelist.xml << 'EOF'
<?xml version="1.0" encoding="utf-8"?>
<whitelist>
  <command name="/usr/bin/python3 -s /usr/bin/firewall-cmd*"/>
  <user id="0"/>
</whitelist>
EOF

grep -q "^Lockdown=" /etc/firewalld/firewalld.conf || echo "Lockdown=yes" >> /etc/firewalld/firewalld.conf
sed -i 's/^Lockdown=.*/Lockdown=yes/' /etc/firewalld/firewalld.conf
firewall-cmd --reload
```

---

↑ [Back to TOC](#table-of-contents)

## Part 4 — Node 3 (Database Server) Configuration

```bash
podman exec -it node3 bash
```

### Step 4.1 — Zone assignment

```bash
firewall-cmd --zone=internal --add-interface=eth0 --permanent
firewall-cmd --reload
```

### Step 4.2 — Internal zone: PostgreSQL from node2 only; SSH from management only

```bash
# Remove default services
firewall-cmd --zone=internal --remove-service=ssh --permanent 2>/dev/null || true
firewall-cmd --zone=internal --remove-service=dhcpv6-client --permanent 2>/dev/null || true

# Allow PostgreSQL from node2 only
firewall-cmd --zone=internal --add-rich-rule='
  rule family="ipv4"
  source address="172.20.2.20"
  port port="5432" protocol="tcp"
  accept' --permanent

# Allow SSH from management host only
firewall-cmd --zone=internal --add-rich-rule='
  rule family="ipv4"
  source address="172.20.3.30"
  service name="ssh"
  accept' --permanent

# Allow ICMP from management host only
firewall-cmd --zone=internal --add-rich-rule='
  rule family="ipv4"
  source address="172.20.3.30"
  protocol value="icmp"
  accept' --permanent

# Set target to DROP
firewall-cmd --zone=internal --set-target=DROP --permanent

firewall-cmd --set-log-denied=all
firewall-cmd --reload
firewall-cmd --zone=internal --list-all
```

### Step 4.3 — Lockdown on node3

```bash
cat > /etc/firewalld/lockdown-whitelist.xml << 'EOF'
<?xml version="1.0" encoding="utf-8"?>
<whitelist>
  <command name="/usr/bin/python3 -s /usr/bin/firewall-cmd*"/>
  <user id="0"/>
</whitelist>
EOF

grep -q "^Lockdown=" /etc/firewalld/firewalld.conf || echo "Lockdown=yes" >> /etc/firewalld/firewalld.conf
sed -i 's/^Lockdown=.*/Lockdown=yes/' /etc/firewalld/firewalld.conf
firewall-cmd --reload
```

---

↑ [Back to TOC](#table-of-contents)

## Part 5 — Auditd Configuration (All Nodes)

Run these commands on each node:

```bash
# Each node:
dnf install -y audit 2>/dev/null || true
systemctl enable --now auditd

# Watch firewalld config for changes
auditctl -w /etc/firewalld/ -p wa -k firewall-config-change

# Persist across reboots
cat >> /etc/audit/rules.d/firewalld.rules << 'EOF'
-w /etc/firewalld/ -p wa -k firewall-config-change
-w /usr/lib/firewalld/ -p wa -k firewall-pkg-change
EOF
```

---

↑ [Back to TOC](#table-of-contents)

## Part 6 — Verification Tests

Run all verification tests from the **host machine** unless noted.

### Test 6.1 — External zone enforcement (node1)

```bash
podman exec node1 bash -c "
  echo '=== External zone services ==='
  firewall-cmd --zone=external --list-all
  echo '=== Target ==='
  firewall-cmd --zone=external --get-target
  echo '=== Masquerade ==='
  firewall-cmd --zone=external --query-masquerade
"
```

Expected: services = http https, target = DROP, masquerade = yes

### Test 6.2 — Port forward is present

```bash
podman exec node1 bash -c "
  firewall-cmd --zone=external --list-forward-ports
"
```

Expected: two entries forwarding 443→8080 and 80→8080 to 172.20.2.20

### Test 6.3 — Connectivity node1 → node2 (HTTP)

```bash
podman exec node1 bash -c "
  curl --connect-timeout 3 http://172.20.2.20:8080 2>&1 | head -5 || echo 'Connection attempt made'
"
```

### Test 6.4 — node2 cannot reach node3 on disallowed ports

```bash
podman exec node2 bash -c "
  # This should be blocked (only 5432 is allowed, and only from node2's IP)
  # Try port 22 from node2 to node3
  curl --connect-timeout 2 http://172.20.3.30:22 2>&1 || echo 'Blocked as expected'
"
```

### Test 6.5 — LogDenied produces journal entries

```bash
# Generate some denied traffic from node2 toward node3 on a blocked port
podman exec node2 bash -c "
  curl --connect-timeout 2 http://172.20.3.30:9999 2>/dev/null || true
"

# Check node3's journal for the log entry
podman exec node3 bash -c "
  journalctl -k --grep='filter_IN' --since='1 minute ago'
"
```

### Test 6.6 — Lockdown is active

```bash
for node in node1 node2 node3; do
  echo -n "$node lockdown: "
  podman exec $node firewall-cmd --query-lockdown
done
```

Expected: all return `yes`

### Test 6.7 — nftables rate-limit table on node1

```bash
podman exec node1 bash -c "
  nft list table inet http_guard
"
```

Expected: table with `burst_blocked` set and `input_http_guard` chain at priority -2

### Test 6.8 — nftables ruleset shows both tables on node1

```bash
podman exec node1 bash -c "
  nft list ruleset | grep '^table'
"
```

Expected output includes:
```
table inet firewalld { ...
table inet http_guard { ...
```

### Test 6.9 — Audit rules are in place

```bash
for node in node1 node2 node3; do
  echo "=== $node ==="
  podman exec $node bash -c "auditctl -l 2>/dev/null | grep firewall || echo 'auditd not running'"
done
```

### Test 6.10 — Policy forwarding works

```bash
podman exec node1 bash -c "
  firewall-cmd --list-all-policies
"
```

Expected: policies `ext-to-dmz`, `dmz-to-ext`, `int-to-ext`

---

↑ [Back to TOC](#table-of-contents)

## Part 7 — Hardening Review Checklist

Use this checklist as a self-assessment. Every item should be ✅.

### node1 (Gateway)

- [ ] `external` zone target = DROP
- [ ] `external` zone services = http, https only
- [ ] Masquerade enabled on `external` zone
- [ ] Port forwards for 80→8080 and 443→8080 to node2
- [ ] Policies: ext-to-dmz, dmz-to-ext, int-to-ext
- [ ] ICMP blocks on external (echo-request, echo-reply)
- [ ] Rate limiting table `http_guard` present in nftables
- [ ] LogDenied = all
- [ ] Lockdown = yes
- [ ] Auditd watching `/etc/firewalld/`
- [ ] No SSH in external zone

### node2 (Web/App)

- [ ] `dmz` zone target = DROP
- [ ] Port 8080 allowed only from node1's DMZ IP (172.20.2.10)
- [ ] ICMP allowed only from node1's DMZ IP (172.20.2.10)
- [ ] SSH allowed only from management host (172.20.3.30)
- [ ] LogDenied = all
- [ ] Lockdown = yes
- [ ] Auditd watching `/etc/firewalld/`

### node3 (Database)

- [ ] `internal` zone target = DROP
- [ ] Port 5432 allowed only from node2's IP (172.20.2.20)
- [ ] SSH allowed only from management host (172.20.3.30)
- [ ] ICMP allowed only from management host (172.20.3.30)
- [ ] No other ports open
- [ ] LogDenied = all
- [ ] Lockdown = yes
- [ ] Auditd watching `/etc/firewalld/`

---

↑ [Back to TOC](#table-of-contents)

## Part 8 — nftables Deep-Dive Verification

Perform these checks to verify the nftables layer matches the firewalld configuration.

### 8.1 — Verify DROP target on all three nodes

```bash
# On each node, confirm the zone chain ends with drop
for node in node1 node2 node3; do
  echo "=== $node ==="
  podman exec $node bash -c "
    for zone in \$(firewall-cmd --get-active-zones | grep -v interfaces); do
      target=\$(firewall-cmd --zone=\$zone --get-target 2>/dev/null)
      echo \"Zone: \$zone  Target: \$target\"
    done
  "
done
```

### 8.2 — Verify rich rule presence in nftables on node2

```bash
podman exec node2 bash -c "
  nft list chain inet firewalld filter_IN_dmz_allow
"
```

Expected: rules matching `ip saddr 172.20.2.10` for TCP 8080 and ICMP

### 8.3 — Verify NAT chain on node1

```bash
podman exec node1 bash -c "
  nft list chain inet firewalld nat_POST_external
"
```

Expected: `masquerade` statement in the chain

### 8.4 — Verify DNAT for port forward on node1

```bash
podman exec node1 bash -c "
  nft list chain inet firewalld nat_PRE_external
"
```

Expected: DNAT rules redirecting 443 and 80 to 172.20.2.20:8080

---

↑ [Back to TOC](#table-of-contents)

## Part 9 — Bonus Challenges

These are optional extensions for students who want to go further.

### Bonus 1 — IPv6 support

Extend the configuration to handle IPv6 traffic:
- Assign IPv6 addresses to container interfaces
- Configure firewalld zones to accept/reject IPv6 traffic appropriately
- Update rich rules and rate-limiting to cover `ip6 saddr`

### Bonus 2 — IPSet-based blocklist

```bash
# Create a GeoIP-style blocklist using ipsets on node1
firewall-cmd --new-ipset=country-block --type=hash:net --permanent
firewall-cmd --ipset=country-block --add-entry=192.0.2.0/24 --permanent
firewall-cmd --ipset=country-block --add-entry=198.51.100.0/24 --permanent

# Block all traffic from the set
firewall-cmd --zone=external --add-rich-rule='
  rule source ipset="country-block" drop' --permanent

firewall-cmd --reload
```

### Bonus 3 — nftables flowtable for node1 forwarding

```bash
# Add a flowtable on node1 to offload established forwarded connections
cat > /etc/nftables.d/flowtable.nft << 'EOF'
table inet fastpath {
    flowtable ft {
        hook ingress priority filter;
        devices = { eth0, eth1, eth2 };
    }
    chain forward {
        type filter hook forward priority filter;
        ip protocol { tcp, udp } flow offload @ft
    }
}
EOF

nft -f /etc/nftables.d/flowtable.nft
nft list flowtable inet fastpath ft
```

### Bonus 4 — Automated compliance check script

Write a shell script that:
1. Iterates over all three nodes
2. Checks each item in the Part 7 checklist
3. Outputs PASS/FAIL per item
4. Returns exit code 0 if all pass, 1 if any fail

---

↑ [Back to TOC](#table-of-contents)

## Part 10 — Capstone Teardown

```bash
# Reset all nodes to clean state
~/firewalld-lab/reset-lab.sh

# Verify clean state
for node in node1 node2 node3; do
  echo "=== $node after reset ==="
  podman exec $node firewall-cmd --get-default-zone
  podman exec $node firewall-cmd --zone=public --list-all
done
```

---

↑ [Back to TOC](#table-of-contents)

## Capstone Completion Criteria

You have successfully completed the capstone if:

1. All items in the Part 7 checklist are ✅
2. All Part 6 verification tests pass
3. Part 8 nftables verification commands show expected output
4. You can explain **why** each rule exists and **which module** taught it
5. You can recover any node from a simulated locked-out state using `podman exec`

---

↑ [Back to TOC](#table-of-contents)

## Skills Demonstrated

By completing this capstone, you have demonstrated:

| Skill | Evidence |
|-------|---------|
| Zone design | Three-zone topology with correct interface assignments |
| Service/port control | Precise allow-lists per tier with DROP defaults |
| Rich rules | Source-restricted access to 8080, 5432, SSH |
| NAT/masquerade | Internet forwarding for DMZ and Internal |
| Port forwarding | DNAT from external 443/80 to internal 8080 |
| Inter-zone policies | Three policies governing forwarding paths |
| Logging | LogDenied=all on all nodes; journal verification |
| Rate limiting | Custom nftables meter with dynamic auto-block set |
| Lockdown | D-Bus protection on all three nodes |
| Auditd integration | Config-change audit rules on all nodes |
| nftables fluency | Direct nft verification of every firewalld decision |
| Troubleshooting | Five-question methodology applied in verification tests |

---

*Congratulations on completing the firewalld course!*  
*See [cheatsheet.md](cheatsheet.md) for a quick-reference summary and [faq.md](faq.md) for answers to common questions.*

---

© 2026 UncleJS — Licensed under CC BY-NC-SA 4.0

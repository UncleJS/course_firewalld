# Module 06 — Rich Rules
[![CC BY-NC-SA 4.0](https://img.shields.io/badge/License-CC%20BY--NC--SA%204.0-lightgrey)](./LICENSE.md)
[![RHEL 10](https://img.shields.io/badge/platform-RHEL%2010-red)](https://access.redhat.com/products/red-hat-enterprise-linux)
[![firewalld](https://img.shields.io/badge/firewalld-RHEL%2010-orange)](https://access.redhat.com/products/red-hat-enterprise-linux)

> **Goal:** Master the rich rule language — firewalld's most expressive rule
> syntax. Rich rules let you combine source/destination matching, service/port
> matching, logging, and auditing in a single statement, with priority control
> and timeout support. They bridge the gap between simple service rules and
> complex per-IP policy enforcement.

---

## Table of Contents

1. [1. Why Rich Rules?](#1-why-rich-rules)
2. [2. Rich Rule Grammar](#2-rich-rule-grammar)
3. [3. Match Elements](#3-match-elements)
4. [4. Actions](#4-actions)
5. [5. Logging and Auditing](#5-logging-and-auditing)
6. [6. Priority Ordering](#6-priority-ordering)
7. [7. Timeout (Temporary) Rules](#7-timeout-temporary-rules)
8. [8. Rich Rules in Zones vs Policies](#8-rich-rules-in-zones-vs-policies)
9. [9. Practical Rich Rule Patterns](#9-practical-rich-rule-patterns)
10. [10. Rich Rule XML Format](#10-rich-rule-xml-format)
11. [11. Troubleshooting Rich Rules](#11-troubleshooting-rich-rules)
12. [Lab 6 — Per-IP Control and Logging](#lab-6-per-ip-control-and-logging)

---

↑ [Back to TOC](#table-of-contents)

## 1. Why Rich Rules?

Zone services and ports are coarse-grained: "allow HTTP from everywhere in this
zone." Policies add direction. Rich rules add precision:

- Allow HTTP, but **only from this specific subnet**
- Allow SSH, but **log every new connection**
- Drop traffic from a specific IP, but **reject (not drop) everything else**
- Allow a source IP through for **2 hours**, then automatically revert
- Accept packets, but **audit** them for compliance logging
- Combine multiple conditions: family=IPv4, source=X, destination=Y, port=Z

Rich rules can be attached to both **zones** and **policies**. They follow the
same two-layer (runtime/permanent) model as all other firewalld configuration.

---

↑ [Back to TOC](#table-of-contents)

## 2. Rich Rule Grammar

The rich rule language is a structured string syntax. The full grammar:

```
rule [family="ipv4|ipv6"] [priority="N"]
  [source [not] address="addr[/mask]" | mac="mac" | ipset="setname"]
  [destination [not] address="addr[/mask]"]
  [service name="svcname" |
   port port="portspec" protocol="tcp|udp|sctp|dccp" |
   protocol value="proto" |
   icmp-type name="icmptype" |
   icmp-block name="icmptype" |
   masquerade |
   forward-port port="port" protocol="proto" to-port="port" [to-addr="addr"]]
  [log [prefix="text"] [level="loglevel"] [limit value="rate/duration"]]
  [audit [type="type"] [limit value="rate/duration"]]
  [accept | reject [type="rejecttype"] | drop | mark set="value"]
```

Every element is optional except the final action. Conditions are combined with
implicit AND — a packet must match all specified conditions.

---

↑ [Back to TOC](#table-of-contents)

## 3. Match Elements

### `family` — address family

```
rule family="ipv4" ...   # IPv4 packets only
rule family="ipv6" ...   # IPv6 packets only
# Omit family to match both
```

Without `family`, the rule applies to both IPv4 and IPv6. Specifying `family`
is required when using IPv4-only or IPv6-only addresses.

### `source` — match source address

```
# Match a specific IP
rule family="ipv4" source address="203.0.113.5" ...

# Match a subnet
rule family="ipv4" source address="10.0.0.0/8" ...

# IPv6 prefix
rule family="ipv6" source address="2001:db8::/32" ...

# MAC address (only in zones, not policies)
rule source mac="aa:bb:cc:dd:ee:ff" ...

# Match traffic from an IP set
rule family="ipv4" source ipset="my_blocklist" ...

# Negate (match everything EXCEPT this source)
rule family="ipv4" source NOT address="192.168.1.0/24" ...
```

### `destination` — match destination address

```
# Match a specific destination IP
rule family="ipv4" destination address="192.168.1.100" ...

# Negate destination
rule family="ipv4" destination NOT address="10.0.0.0/8" ...
```

Destination matching in zone rules is less common but useful for multi-homed
hosts where you want rules to apply only to traffic destined for a specific
interface IP.

### `service` — match by service name

```
rule family="ipv4" source address="10.0.0.0/8" service name="ssh" accept
```

### `port` — match by port and protocol

```
rule family="ipv4" port protocol="tcp" port="8080" accept
rule family="ipv4" port protocol="tcp" port="8000-8099" accept
rule family="ipv4" port protocol="udp" port="53" accept
```

### `protocol` — match by IP protocol

```
rule protocol value="gre" accept
rule protocol value="esp" accept
```

### `icmp-type` — match specific ICMP type

```
rule icmp-type name="echo-request" drop
rule family="ipv6" icmp-type name="router-advertisement" accept
```

---

↑ [Back to TOC](#table-of-contents)

## 4. Actions

### `accept`

Forward or deliver the packet. Processing stops for this packet.

```
rule family="ipv4" source address="192.168.1.0/24" service name="http" accept
```

### `reject`

Send back an ICMP error and discard the packet. The connection fails
immediately (not a timeout).

```
# Default reject type
rule family="ipv4" source address="198.51.100.0/24" reject

# Specific reject type
rule family="ipv4" source address="198.51.100.0/24" \
  reject type="icmp-host-prohibited"
```

Available reject types:
- `icmp-net-unreachable`
- `icmp-host-unreachable`
- `icmp-port-unreachable` (most common for TCP)
- `icmp-proto-unreachable`
- `icmp-net-prohibited`
- `icmp-host-prohibited`
- `icmp-admin-prohibited`
- `tcp-reset` (TCP RST — for TCP only)

### `drop`

Silently discard. The sender gets no feedback — the connection times out.

```
rule family="ipv4" source address="198.51.100.0/24" drop
```

Use `drop` for hostile/attacking sources where you don't want to acknowledge
the host's existence.

### `mark`

Set a packet mark (used for advanced routing decisions, QoS, or working with
other subsystems):

```
rule family="ipv4" source address="10.100.0.0/16" mark set="0x1"
```

---

↑ [Back to TOC](#table-of-contents)

## 5. Logging and Auditing

Logging and auditing can be combined with any action. They are executed *before*
the action — so you log the packet, then accept or drop it.

### `log`

Logs the packet to the kernel log (visible in `journalctl`):

```
rule family="ipv4" source address="10.0.0.0/8" service name="ssh" \
  log prefix="SSH-INTERNAL: " level="info" accept
```

Log levels: `emerg`, `alert`, `crit`, `error`, `warning`, `notice`, `info`,
`debug`

Rate limiting with `limit`:

```
# Log at most 3 entries per minute (prevents log flooding)
rule family="ipv4" source address="0.0.0.0/0" service name="ssh" \
  log prefix="SSH-ATTEMPT: " level="warning" limit value="3/m" accept
```

Rate limit format: `N/s` (per second), `N/m` (per minute), `N/h` (per hour),
`N/d` (per day)

### `audit`

Sends records to the Linux audit system (`auditd`), which writes to
`/var/log/audit/audit.log`. Useful for compliance requirements that mandate
audit trail:

```
rule family="ipv4" source address="10.0.0.0/8" service name="ssh" \
  audit type="accept" limit value="1/s" accept
```

Audit types: `accept`, `deny`

### Combining log + audit + accept

A packet can trigger a log message, an audit record, AND be accepted — all in
one rule:

```
rule family="ipv4" source address="203.0.113.0/24" service name="https" \
  log prefix="EXTERNAL-HTTPS: " level="info" limit value="10/m" \
  audit type="accept" \
  accept
```

---

↑ [Back to TOC](#table-of-contents)

## 6. Priority Ordering

Rich rules within a zone or policy are evaluated in **priority order**. Priority
is an integer in the range **-32768 to 32767**. Lower numbers run first.

```
rule priority="-100" family="ipv4" source address="203.0.113.5" service name="ssh" accept
rule priority="0"    family="ipv4" service name="ssh" \
  log prefix="SSH: " level="warning" reject
```

With these two rules (both on the same zone):
1. Priority -100: if source is 203.0.113.5, accept SSH → **admin IP gets access**
2. Priority 0: reject all other SSH with logging → **everyone else is rejected**

Without priorities, rules are evaluated in the order they were added.

> **⚠️  IMPORTANT — Priority and zone services interact**
> Zone-level services (added with `--add-service`) are internally represented
> as rules with a very high positive priority (after rich rules). This means
> rich rules with negative priorities run before service rules. Rich rules
> with positive priorities run after them.
>
> Use **negative priorities** for rules that should override services.
> Use **positive priorities** for rules that should be a last resort.

---

↑ [Back to TOC](#table-of-contents)

## 7. Timeout (Temporary) Rules

Rich rules can include `--timeout`, making them automatically expire:

```bash
# Block an attacking IP for 30 minutes, then automatically remove the block
firewall-cmd --zone=public --add-rich-rule='
  rule family="ipv4" source address="198.51.100.1" drop
' --timeout=30m

# Allow temporary access for maintenance
firewall-cmd --zone=public --add-rich-rule='
  rule family="ipv4" source address="203.0.113.50" service name="ssh" accept
' --timeout=2h

# Valid timeout units: s (seconds), m (minutes), h (hours), d (days)
```

Timeout rules are runtime only — they cannot be combined with `--permanent`.

This is extremely useful for incident response: block an attacker now, and the
rule cleans itself up automatically rather than leaving a permanent rule behind.

---

↑ [Back to TOC](#table-of-contents)

## 8. Rich Rules in Zones vs Policies

Rich rules work identically in both zones and policies:

```bash
# Rich rule in a zone
firewall-cmd --permanent --zone=public --add-rich-rule='
  rule family="ipv4" source address="10.0.0.0/8" service name="ssh" accept
'

# Rich rule in a policy
firewall-cmd --permanent --policy internet_to_host --add-rich-rule='
  rule family="ipv4" source address="203.0.113.5" service name="ssh" accept
'

# List rich rules
firewall-cmd --zone=public --list-rich-rules
firewall-cmd --permanent --policy internet_to_host --list-rich-rules

# Remove a rich rule (quote it exactly as it was added)
firewall-cmd --permanent --zone=public --remove-rich-rule='
  rule family="ipv4" source address="10.0.0.0/8" service name="ssh" accept
'
```

---

↑ [Back to TOC](#table-of-contents)

## 9. Practical Rich Rule Patterns

### Pattern 1: Allow service from specific subnet only

```bash
# SSH only from management network
firewall-cmd --permanent --zone=public --add-rich-rule='
  rule priority="-100" family="ipv4"
  source address="10.100.0.0/24"
  service name="ssh"
  accept
'

# Then change the zone's default SSH service to deny
firewall-cmd --permanent --zone=public --remove-service=ssh
```

### Pattern 2: Log + accept for auditing

```bash
# Log all new SSH connections from anywhere
firewall-cmd --permanent --zone=public --add-rich-rule='
  rule family="ipv4"
  service name="ssh"
  log prefix="SSH-NEW-CONN: " level="info" limit value="5/m"
  accept
'
```

### Pattern 3: Block + log a specific IP (incident response)

```bash
# Log and drop attacker (runtime, expires in 1 hour)
firewall-cmd --zone=public --add-rich-rule='
  rule family="ipv4"
  source address="198.51.100.50"
  log prefix="BLOCKED-ATTACKER: " level="warning" limit value="3/m"
  drop
' --timeout=1h
```

### Pattern 4: Restrict service to MAC address

```bash
# Only allow HTTP from a specific MAC address (useful in LAN segments)
firewall-cmd --permanent --zone=internal --add-rich-rule='
  rule source mac="aa:bb:cc:dd:ee:ff"
  service name="http"
  accept
'
```

### Pattern 5: Reject with TCP reset

```bash
# Fast-fail connections to a blocked port (TCP RST instead of timeout)
firewall-cmd --permanent --zone=public --add-rich-rule='
  rule family="ipv4"
  port protocol="tcp" port="23"
  reject type="tcp-reset"
'
```

### Pattern 6: Rate limit new connections (basic DDoS protection)

```bash
# Limit SSH new connections to 3 per minute per source IP
# (This uses rich rule logging's limit — not a true rate limit per source)
# For per-source rate limiting, use nftables meters (Module 12) or IP sets (Module 09)
firewall-cmd --permanent --zone=public --add-rich-rule='
  rule family="ipv4"
  service name="ssh"
  log prefix="SSH-RATE: " level="info" limit value="3/m"
  accept
'
```

### Pattern 7: Forward port with source restriction

```bash
# Forward port 80 to backend, but only for traffic from the DMZ
firewall-cmd --permanent --zone=dmz --add-rich-rule='
  rule family="ipv4"
  source address="172.20.2.0/24"
  forward-port port="80" protocol="tcp" to-port="8080" to-addr="172.20.3.100"
'
```

---

↑ [Back to TOC](#table-of-contents)

## 10. Rich Rule XML Format

Rich rules in zone and policy XML files:

```xml
<!-- In /etc/firewalld/zones/public.xml -->
<zone>
  ...
  <!-- Accept SSH from admin network (priority -100) -->
  <rule priority="-100">
    <source address="10.100.0.0/24"/>
    <service name="ssh"/>
    <accept/>
  </rule>

  <!-- Log and reject everything else trying SSH -->
  <rule priority="0">
    <service name="ssh"/>
    <log prefix="SSH-BLOCKED: " level="warning">
      <limit value="3/m"/>
    </log>
    <reject type="tcp-reset"/>
  </rule>

  <!-- Temporary block (note: cannot persist timeout in XML) -->
  <rule>
    <source address="198.51.100.50"/>
    <drop/>
  </rule>
</zone>
```

---

↑ [Back to TOC](#table-of-contents)

## 11. Troubleshooting Rich Rules

### Rule not matching — quoting issues

Rich rules must be quoted carefully in the shell. Single quotes protect the
inner double quotes:

```bash
# CORRECT
firewall-cmd --zone=public --add-rich-rule='rule family="ipv4" source address="10.0.0.1" accept'

# WRONG — inner quotes not protected
firewall-cmd --zone=public --add-rich-rule="rule family="ipv4" source address="10.0.0.1" accept"
```

### Removing rules — exact match required

To remove a rich rule, you must provide the exact string you used to add it:

```bash
# Added with this:
firewall-cmd --permanent --zone=public --add-rich-rule='rule family="ipv4" source address="10.0.0.0/8" service name="ssh" accept'

# Must remove with exact same string:
firewall-cmd --permanent --zone=public --remove-rich-rule='rule family="ipv4" source address="10.0.0.0/8" service name="ssh" accept'
```

### Checking what nftables rule was created

```bash
nft list chain inet firewalld filter_IN_public
# Look for the IP/port in the rules
```

### Listing all rich rules

```bash
# All rich rules in a zone
firewall-cmd --zone=public --list-rich-rules

# With permanent config
firewall-cmd --permanent --zone=public --list-rich-rules

# In a policy
firewall-cmd --policy mypolicy --list-rich-rules
```

---

↑ [Back to TOC](#table-of-contents)

## Lab 6 — Per-IP Control and Logging

**Topology:** Single-node (node1)

**Objective:** Use rich rules to implement tiered access: one IP gets full SSH
access, another gets limited access with logging, and all others are rejected.
Observe exactly which log messages appear and which nftables rules are created.

---

### Step 1 — Start node1 and prepare

```bash
# 🔧 LAB STEP
podman exec -it node1 bash

# Confirm we're starting from default state
firewall-cmd --list-all --zone=public
```

---

### Step 2 — Remove default SSH service (take full control)

```bash
# 🔧 LAB STEP
# We'll control SSH entirely with rich rules
firewall-cmd --zone=public --remove-service=ssh

# Verify SSH is now blocked
firewall-cmd --list-services --zone=public
```

---

### Step 3 — Add a high-priority allow for admin IP

```bash
# 🔧 LAB STEP
# Note: 172.20.1.1 is the Podman network gateway — it is the IP address
# that host-machine traffic appears to come from when connecting into node1
# (i.e., when you run nc/curl from the host, the container sees 172.20.1.1
# as the source, not your host's real IP).  It is NOT node1's own address.
firewall-cmd --zone=public --add-rich-rule='
  rule priority="-200" family="ipv4"
  source address="172.20.1.1"
  service name="ssh"
  log prefix="SSH-ADMIN-ALLOW: " level="info" limit value="3/m"
  accept
'
```

---

### Step 4 — Add a rate-limited log for other IPs

```bash
# 🔧 LAB STEP
firewall-cmd --zone=public --add-rich-rule='
  rule priority="0" family="ipv4"
  service name="ssh"
  log prefix="SSH-DENIED: " level="warning" limit value="3/m"
  reject type="tcp-reset"
'
```

---

### Step 5 — List all rich rules to verify

```bash
# 🔧 LAB STEP
firewall-cmd --list-rich-rules --zone=public
```

---

### Step 6 — Test access and observe logs

```bash
# 🔧 LAB STEP (from host — simulating admin access via 172.20.1.1 gateway)
# Note: your host's connection appears from 172.20.1.1 (the network gateway)
nc -zv 172.20.1.10 22
# Should succeed (or fail with Connection refused if no SSH daemon, but port is open)

# Simulate a blocked source (different subnet)
# (This requires a second terminal on another network — use node2 if available)
```

---

### Step 7 — Read log messages

```bash
# 🔧 LAB STEP (inside node1)
# Watch the journal for our log prefixes
journalctl -f -k | grep -E "SSH-ADMIN|SSH-DENIED"
```

Generate some traffic from the host to trigger log entries.

---

### Step 8 — Inspect nftables rules

```bash
# 🔧 LAB STEP (inside node1)
nft list chain inet firewalld filter_IN_public
```

> **💡 CONCEPT CHECK**
> You should see:
> 1. A rule with priority matching your admin allow rule
> 2. A log and reject rule for blocked SSH
> Notice the ordering in nftables matches the priority numbers — lower priority
> number (more negative) = earlier in the chain.

---

### Step 9 — Add a timeout block for an "attacker"

```bash
# 🔧 LAB STEP (inside node1)
# Simulate blocking an attacker for 120 seconds
firewall-cmd --zone=public --add-rich-rule='
  rule family="ipv4"
  source address="198.51.100.99"
  log prefix="ATTACKER-BLOCKED: " level="warning" limit value="1/m"
  drop
' --timeout=120

# Verify it's in the ruleset
firewall-cmd --list-rich-rules --zone=public

# Wait 30 seconds and check again — still there
sleep 30 && firewall-cmd --list-rich-rules --zone=public
```

---

### Step 10 — Make rules permanent and clean up

```bash
# 🔧 LAB STEP

# Make the admin allow permanent
firewall-cmd --permanent --zone=public --add-rich-rule='
  rule priority="-200" family="ipv4"
  source address="172.20.1.1"
  service name="ssh"
  log prefix="SSH-ADMIN-ALLOW: " level="info" limit value="3/m"
  accept
'

# Re-add SSH service as a fallback (for non-rich-rule evaluation)
firewall-cmd --permanent --zone=public --add-service=ssh

# Clean up the reject rule (it was runtime only)
# (Will disappear after reload — just reload)
firewall-cmd --reload

# Final state
firewall-cmd --list-all --zone=public
```

---

### Summary

Rich rules give you surgical control:

| Capability | Command element |
|------------|-----------------|
| IPv4 only | `family="ipv4"` |
| Source IP match | `source address="..."` |
| Source IP negate | `source NOT address="..."` |
| Log + action | `log prefix="..." accept` |
| Rate limit logging | `log ... limit value="3/m"` |
| Priority ordering | `priority="-200"` |
| Temporary rule | `--timeout=2h` |
| TCP fast-fail | `reject type="tcp-reset"` |

---

*Module 06 complete.*

**Continue to [Module 07 — NAT, Masquerading, and Port Forwarding →](./07-nat-masquerading-and-port-forwarding.md)**

---

© 2026 UncleJS — Licensed under CC BY-NC-SA 4.0

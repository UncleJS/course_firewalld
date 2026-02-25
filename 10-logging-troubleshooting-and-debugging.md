# Module 10 — Logging, Troubleshooting, and Debugging

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Learning Objectives](#learning-objectives)
3. [10.1 — The Logging Stack](#101-the-logging-stack)
4. [10.2 — firewalld Log Levels](#102-firewalld-log-levels)
5. [10.3 — nftables Tracing](#103-nftables-tracing)
6. [10.4 — Systematic Troubleshooting Methodology](#104-systematic-troubleshooting-methodology)
7. [10.5 — State and Configuration Consistency Checks](#105-state-and-configuration-consistency-checks)
8. [10.6 — Common Problems and Solutions](#106-common-problems-and-solutions)
9. [10.7 — Recovering from a Locked-Out State](#107-recovering-from-a-locked-out-state)
10. [10.8 — Performance Profiling](#108-performance-profiling)
11. [10.9 — Audit Logging via auditd](#109-audit-logging-via-auditd)
12. [Lab 10 — Logging and Troubleshooting in Practice](#lab-10-logging-and-troubleshooting-in-practice)
13. [Key Takeaways](#key-takeaways)

---

↑ [Back to TOC](#table-of-contents)

## Prerequisites
- Modules 01–09 completed
- Lab environment running (`~/firewalld-lab/start-lab.sh`)
- Familiarity with `journalctl`, `nft`, and firewalld zones

---

↑ [Back to TOC](#table-of-contents)

## Learning Objectives
By the end of this module you will be able to:
1. Enable and configure firewalld's built-in logging at multiple verbosity levels
2. Use `nft` to add temporary trace/audit rules
3. Read and interpret `journald` firewall log entries
4. Correlate firewalld log messages with the underlying nftables rule that fired
5. Apply a systematic troubleshooting methodology for "traffic not passing" scenarios
6. Use `firewall-cmd --debug` and `firewalld --debug` to trace daemon decisions
7. Profile firewalld performance and identify slow-rule scenarios
8. Reset/recover a misconfigured firewall without losing access

---

↑ [Back to TOC](#table-of-contents)

## 10.1 — The Logging Stack

Traffic decisions in RHEL 10 flow through three layers, each capable of producing logs:

```
Packet arrives
      │
      ▼
  nftables (kernel)  ──► kernel log → journald (transport=syslog or audit)
      │
      ▼
  firewalld (daemon) ──► firewalld.log / journald unit log
      │
      ▼
  Application        ──► /var/log/app.log etc.
```

Understanding **which layer** generated a message is the first step in any diagnosis.

---

↑ [Back to TOC](#table-of-contents)

## 10.2 — firewalld Log Levels

firewalld has its own concept of "LogDenied" (what gets logged when a packet is dropped/rejected) plus a daemon-level debug verbosity.

### 10.2.1 LogDenied

`LogDenied` controls whether denied packets emit a kernel log message.  
Values: `off` (default) | `unicast` | `broadcast` | `multicast` | `all`

```bash
# Show current setting
firewall-cmd --get-log-denied

# Enable logging for all denied packets
firewall-cmd --set-log-denied=all

# Make permanent
firewall-cmd --set-log-denied=all --permanent
firewall-cmd --reload
```

> **Concept — runtime vs permanent**: `--set-log-denied` without `--permanent` changes the running daemon only. After `--reload` the permanent value takes effect. Always set both or set permanent and reload.

When `LogDenied` is active, dropped packets generate a kernel log line via nftables' `log` statement.  
The nftables rule firewalld injects looks like:

```
# nft list ruleset | grep -A3 "log prefix"
chain filter_IN_public_deny {
    log prefix "filter_IN_public_deny: " level info
    reject with icmpx admin-prohibited
}
```

### 10.2.2 Reading LogDenied entries in journald

```bash
journalctl -k --grep="filter_IN" --since="5 minutes ago"
```

A typical line:
```
Feb 24 10:15:42 node1 kernel: filter_IN_public_deny: IN=eth0 OUT= MAC=...
  SRC=172.20.1.50 DST=172.20.1.1 LEN=60 TOS=0x00 PREC=0x00 TTL=64
  ID=12345 DF PROTO=TCP SPT=54321 DPT=8080 WINDOW=29200 RES=0x00 SYN
```

Field reference:

| Field | Meaning |
|-------|---------|
| `filter_IN_public_deny:` | nftables log prefix → chain name → zone = `public` |
| `IN=eth0` | Ingress interface |
| `OUT=` | Egress interface (empty = input packet) |
| `SRC=` | Source IP |
| `DST=` | Destination IP |
| `PROTO=TCP` | Protocol |
| `DPT=8080` | Destination port (the one that was blocked) |
| `SYN` | TCP flags — this was a connection attempt |

### 10.2.3 Daemon debug logging

```bash
# Temporarily raise firewalld verbosity (no restart needed)
firewall-cmd --debug=2        # 0=off 1=minimal 2=verbose 3=very verbose

# Or start firewalld with debug from the shell (useful in containers)
firewalld --debug=3 --nofork &

# Follow daemon logs
journalctl -u firewalld -f
```

> `--debug` output goes to the firewalld journal unit, not to kernel logs.  
> Use it to trace zone assignment, policy evaluation, and D-Bus calls.

---

↑ [Back to TOC](#table-of-contents)

## 10.3 — nftables Tracing

nftables has a built-in **trace** mechanism (analogous to `iptables --trace`) that records every rule evaluation for matching packets.

### 10.3.1 Enable trace on a specific packet type

```bash
# On node1: trace all new TCP connections to port 8080 from the DMZ
nft add rule inet firewalld filter_INPUT \
    ip saddr 172.20.2.0/24 tcp dport 8080 ct state new \
    meta nftrace set 1

# Watch the trace output (kernel ring buffer)
nft monitor trace
```

Sample trace output:
```
trace id 0x1a2b3c4d inet firewalld filter_INPUT packet: ...
trace id 0x1a2b3c4d inet firewalld filter_INPUT rule 0x1 (verdict continue)
trace id 0x1a2b3c4d inet firewalld filter_IN_ZONES rule 0x5 (verdict goto filter_IN_dmz)
trace id 0x1a2b3c4d inet firewalld filter_IN_dmz rule 0x9 (verdict continue)
trace id 0x1a2b3c4d inet firewalld filter_IN_dmz_allow rule 0x3 (verdict accept)
```

Reading the trace:
- Each line shows: `trace id` → `table` → `chain` → `rule handle` → `verdict`
- `goto filter_IN_dmz` → packet was dispatched to the dmz zone chain
- `verdict accept` → allowed by a rule in `filter_IN_dmz_allow`

### 10.3.2 Remove the trace rule when done

```bash
# List rule handles in filter_INPUT
nft --handle list chain inet firewalld filter_INPUT

# Delete by handle number (e.g. handle 42)
nft delete rule inet firewalld filter_INPUT handle 42
```

> **Warning**: Trace rules generate high log volume under load. Always remove them after debugging.

### 10.3.3 Trace with nft monitor (structured output)

```bash
# Show only accepted packets
nft monitor trace | grep "verdict accept"

# Show packets that hit drop/reject
nft monitor trace | grep -E "verdict (drop|reject)"
```

---

↑ [Back to TOC](#table-of-contents)

## 10.4 — Systematic Troubleshooting Methodology

### The Five Questions

When traffic is not passing, answer these five questions in order:

```
1. Does the packet reach the host?
2. Which interface and zone does it enter?
3. Which chain evaluates it?
4. What verdict does the chain return?
5. If forwarded, is routing correct and does the egress zone allow it?
```

### 10.4.1 Question 1 — Does the packet reach the host?

```bash
# On the sending node — does the packet leave?
tcpdump -i eth0 -n tcp port 8080     # or use nft monitor

# On the receiving node — does it arrive?
tcpdump -i eth0 -n tcp port 8080
```

If the packet never arrives → routing or L2 problem, not firewalld.

### 10.4.2 Question 2 — Interface and zone

```bash
# Which zones are active?
firewall-cmd --get-active-zones

# Which zone handles eth0?
firewall-cmd --get-zone-of-interface=eth0

# Verify at nftables level
nft list chain inet firewalld filter_IN_ZONES | grep eth0
```

### 10.4.3 Question 3 — Which chain evaluates it?

```bash
# List all chains related to a zone
nft list ruleset | grep "chain filter_IN_public"
# → filter_IN_public, filter_IN_public_allow, filter_IN_public_deny

# Trace the packet (see 10.3)
```

### 10.4.4 Question 4 — Verdict

```bash
# Check what rules accept traffic in the zone
firewall-cmd --zone=public --list-all

# Check what nftables actually has (ground truth)
nft list chain inet firewalld filter_IN_public_allow
```

Compare the two: if `firewall-cmd` shows a service but nftables does not have the corresponding rule, the permanent/runtime state is out of sync → `firewall-cmd --reload` may fix it, or daemon restart may be needed.

### 10.4.5 Question 5 — Forwarded traffic

```bash
# Is IP forwarding enabled at the kernel level?
sysctl net.ipv4.ip_forward
sysctl net.ipv6.conf.all.forwarding

# Is masquerade/NAT in place?
firewall-cmd --zone=external --query-masquerade

# Which policy governs the forward path?
firewall-cmd --list-all-policies
nft list chain inet firewalld filter_FWD_ZONES
```

---

↑ [Back to TOC](#table-of-contents)

## 10.5 — State and Configuration Consistency Checks

### 10.5.1 Runtime vs permanent divergence

```bash
# Compare runtime and permanent for a zone
diff \
  <(firewall-cmd --zone=public --list-all) \
  <(firewall-cmd --zone=public --list-all --permanent)
```

If output differs, runtime was changed without `--permanent` (or vice versa).

### 10.5.2 Validate permanent configuration

```bash
# Test permanent config without applying it
firewall-cmd --check-config

# Output: success  (or error messages)
```

### 10.5.3 Inspect raw XML

Permanent configuration lives in `/etc/firewalld/`.  
Runtime state is in memory (no files).

```bash
# View all permanent zone files
ls /etc/firewalld/zones/

# View a specific zone
cat /etc/firewalld/zones/public.xml

# View service definitions (custom ones)
ls /etc/firewalld/services/
```

### 10.5.4 Daemon status

```bash
systemctl status firewalld

# Full daemon log since last start
journalctl -u firewalld --since "$(systemctl show -p ActiveEnterTimestamp firewalld | cut -d= -f2)"
```

---

↑ [Back to TOC](#table-of-contents)

## 10.6 — Common Problems and Solutions

### Problem 1: Service added but traffic still blocked

**Symptom**: `firewall-cmd --zone=public --list-services` shows the service, but connections are refused.

**Diagnosis**:
```bash
# 1. Confirm runtime has the rule
nft list chain inet firewalld filter_IN_public_allow | grep -i "dport"

# 2. Check the service definition resolves the right port
firewall-cmd --info-service=http
# If custom: cat /etc/firewalld/services/myapp.xml
```

**Common causes**:
- Port in service XML doesn't match what the app listens on
- App bound to `127.0.0.1` only (firewalld can't help here)
- SELinux is blocking the bind (check `ausearch -m avc`)

---

### Problem 2: `--permanent` change not active

**Symptom**: `--permanent` shows the rule, runtime does not.

**Fix**:
```bash
firewall-cmd --reload
```

> `--reload` applies permanent config to runtime. It does **not** restart the daemon and does **not** drop established connections (unlike `--complete-reload`).

---

### Problem 3: `firewall-cmd --reload` wipes a needed runtime rule

**Symptom**: A runtime-only rule (added without `--permanent`) disappears after reload.

**Fix**: Either always use `--permanent` + `--reload`, or track ephemeral rules in a script and re-apply after reload.

---

### Problem 4: Masquerade not working

```bash
# Verify masquerade is in the correct zone (the outgoing-interface zone)
firewall-cmd --zone=external --query-masquerade

# Verify at nftables level
nft list chain inet firewalld nat_POST_external | grep masquerade

# Verify ip_forward
sysctl net.ipv4.ip_forward   # must be 1
```

---

### Problem 5: Zone not assigned to interface

```bash
# Check active zones
firewall-cmd --get-active-zones

# Assign interface if missing
firewall-cmd --zone=internal --add-interface=eth2
firewall-cmd --zone=internal --add-interface=eth2 --permanent
```

---

### Problem 6: After `firewall-cmd --complete-reload`, SSH drops

`--complete-reload` restarts the entire nftables ruleset — this **does** drop established connections.  
Mitigation: Always run `--reload` (not `--complete-reload`) in production.  
Emergency recovery: console/IPMI access, or a scheduled `firewall-cmd --reload` via `at` before running `--complete-reload`.

---

↑ [Back to TOC](#table-of-contents)

## 10.7 — Recovering from a Locked-Out State

If you accidentally block all traffic (including SSH), recovery options in priority order:

### Option A — Console / OOB access
Connect via IPMI/iDRAC/serial and run:
```bash
firewall-cmd --panic-off          # if panic mode was triggered
firewall-cmd --set-default-zone=trusted   # temporary — allow everything
```

### Option B — Scheduled firewall reset (pro-active)

Before making dangerous changes, schedule a reset:
```bash
# Schedule an automatic reload in 5 minutes as a safety net
echo "firewall-cmd --reload" | at now + 5 minutes
# Now make your changes; if you lose access, it auto-resets in 5 min
```

### Option C — Recovery from container (lab context)

```bash
# From the host, exec into the container
podman exec -it node1 bash

# Then reset
firewall-cmd --reload
# or
systemctl restart firewalld
```

### Option D — Reset to defaults

```bash
# Remove all custom config and revert to shipped defaults
rm -rf /etc/firewalld/zones/ /etc/firewalld/services/ /etc/firewalld/policies/ \
       /etc/firewalld/ipsets/ /etc/firewalld/direct.xml
systemctl restart firewalld
```

> This is destructive. Always back up `/etc/firewalld/` first.
> In the lab container context this is safe — the container can be recreated from scratch.
> On a real host this also removes any custom ipsets and direct rules.

---

↑ [Back to TOC](#table-of-contents)

## 10.8 — Performance Profiling

### 10.8.1 Measure rule evaluation overhead

```bash
# Count nftables rules
nft list ruleset | grep -c "^    "

# Time a firewall-cmd operation
time firewall-cmd --reload
```

### 10.8.2 IPSet vs rich-rule performance

As shown in Module 09, IP sets evaluate O(1) regardless of size.  
Rich rules with many source IPs evaluate O(n).  
If you have >20 source IPs, use an ipset.

### 10.8.3 Identify "slow" rules

nftables doesn't have built-in per-rule timing, but you can use packet counters:
```bash
# Add counters to a chain temporarily
nft add rule inet firewalld filter_INPUT counter comment "perf-probe"

# Check packet/byte counts
nft list ruleset | grep -A1 "perf-probe"
```

---

↑ [Back to TOC](#table-of-contents)

## 10.9 — Audit Logging via auditd

For compliance environments, use the kernel audit subsystem instead of (or in addition to) firewalld's LogDenied.

```bash
# Install audit
dnf install -y audit

# Add a firewall-related audit rule — log all nft program executions
auditctl -w /usr/sbin/nft -p x -k firewall-changes
auditctl -w /etc/firewalld/ -p wa -k firewall-config

# Search audit log
ausearch -k firewall-changes --interpret
```

---

↑ [Back to TOC](#table-of-contents)

## Lab 10 — Logging and Troubleshooting in Practice

**Objective**: Enable logging, generate denied traffic, trace it through the stack, and practice the troubleshooting methodology.

### Setup

```bash
# Start the lab if not already running
~/firewalld-lab/start-lab.sh

# Open three terminal windows: node1, node2, node3
podman exec -it node1 bash   # terminal 1
podman exec -it node2 bash   # terminal 2
podman exec -it node3 bash   # terminal 3
```

---

### Step 1 — Enable LogDenied on node1

```bash
# Terminal 1 (node1)
firewall-cmd --set-log-denied=all
firewall-cmd --get-log-denied    # verify: all
```

---

### Step 2 — Generate denied traffic

```bash
# Terminal 2 (node2 — DMZ, 172.20.2.x)
# Try to reach a port that should be blocked on node1
# Note: use node1's actual IP on the DMZ interface (172.20.1.10), not the
# Podman network gateway (172.20.1.1).
curl --connect-timeout 3 http://172.20.1.10:9999 || echo "Blocked as expected"
```

---

### Step 3 — Read the log

```bash
# Terminal 1 (node1)
journalctl -k --grep="filter_IN" --since="1 minute ago"
```

Identify:
- Which chain prefix fired (e.g. `filter_IN_external_deny`)
- Source IP and destination port

---

### Step 4 — Trace the packet with nft monitor

```bash
# Terminal 1 (node1) — add trace rule
nft add rule inet firewalld filter_INPUT \
    ip saddr 172.20.2.0/24 tcp dport 9999 ct state new \
    meta nftrace set 1

# Start monitoring in background
nft monitor trace > /tmp/trace.log &
TRACE_PID=$!
```

```bash
# Terminal 2 (node2) — trigger again
curl --connect-timeout 3 http://172.20.1.10:9999 || true
```

```bash
# Terminal 1 (node1) — examine trace
cat /tmp/trace.log
kill $TRACE_PID

# Clean up trace rule
HANDLE=$(nft --handle list chain inet firewalld filter_INPUT | grep "nftrace set 1" | awk '{print $NF}')
nft delete rule inet firewalld filter_INPUT handle $HANDLE
```

---

### Step 5 — Practice the five questions

**Scenario**: node3 (internal) cannot reach port 8080 on node2 (DMZ).

```bash
# Terminal 3 (node3)
curl --connect-timeout 3 http://172.20.2.20:8080 || echo "Failed"
```

Answer the five questions:

1. **Does the packet reach node2?**
```bash
# Terminal 2 (node2)
tcpdump -i eth0 -n 'tcp port 8080' -c 5
```

2. **Which zone does it enter on node2?**
```bash
# Terminal 2 (node2)
firewall-cmd --get-zone-of-interface=eth0
```

3. **Which chain evaluates it?**
```bash
# Terminal 2 (node2)
nft list chain inet firewalld filter_IN_ZONES | grep eth0
```

4. **What verdict?**
```bash
# Terminal 2 (node2)
firewall-cmd --zone=dmz --list-all
nft list chain inet firewalld filter_IN_dmz_allow
```

5. **Fix it** (allow port 8080 in the dmz zone on node2):
```bash
# Terminal 2 (node2)
firewall-cmd --zone=dmz --add-port=8080/tcp
# Re-test from node3
```

---

### Step 6 — Simulate runtime/permanent divergence

```bash
# Terminal 1 (node1)
# Add a runtime-only rule
firewall-cmd --zone=public --add-port=7777/tcp

# Confirm it's in runtime
firewall-cmd --zone=public --list-ports

# Confirm it's NOT in permanent
firewall-cmd --zone=public --list-ports --permanent

# Reload — rule disappears
firewall-cmd --reload
firewall-cmd --zone=public --list-ports   # 7777 gone
```

---

### Step 7 — Validate config and inspect XML

```bash
# Terminal 1 (node1)
firewall-cmd --check-config

# View the public zone XML
cat /etc/firewalld/zones/public.xml 2>/dev/null || echo "No custom override — using default"

# View the shipped default
cat /usr/lib/firewalld/zones/public.xml
```

---

### Step 8 — Recovery simulation

```bash
# Terminal 1 (node1)
# Accidentally block all input
firewall-cmd --zone=public --set-target=DROP

# Observe — traffic is now dropped
# Recover from the container host
# Terminal (host machine):
podman exec -it node1 firewall-cmd --zone=public --set-target=default
podman exec -it node1 firewall-cmd --reload
```

---

### Step 9 — Cleanup

```bash
# Terminal 1 (node1)
firewall-cmd --set-log-denied=off
```

---

### Lab Verification Checklist

- [ ] `journalctl -k` shows log entries with `filter_IN` prefix when traffic is denied
- [ ] `nft monitor trace` output shows chain traversal for a traced packet
- [ ] Five-question methodology led to identifying and fixing blocked port 8080
- [ ] Runtime-only rule disappeared after `firewall-cmd --reload`
- [ ] `firewall-cmd --check-config` returns `success`
- [ ] Recovery from accidental block succeeded via `podman exec`

---

↑ [Back to TOC](#table-of-contents)

## Key Takeaways

| Topic | Key Point |
|-------|-----------|
| LogDenied | Set to `all` during debugging; `off` in production (noisy) |
| nft trace | Most powerful tool for per-packet chain traversal analysis |
| Five questions | Always work through them in order; don't skip to fixes |
| Runtime vs permanent | `diff` them if behavior is unexpected |
| `--reload` vs `--complete-reload` | `--reload` preserves connections; `--complete-reload` drops them |
| Recovery | Always have console/OOB access; use `at` safety timer |

---

*Next: [Module 11 — Lockdown Mode and Hardening](11-lockdown-mode-and-hardening.md)*

---

© 2026 Jaco Steyn — Licensed under CC BY-SA 4.0

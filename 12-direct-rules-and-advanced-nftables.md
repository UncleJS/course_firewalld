# Module 12 — Direct Rules and Advanced nftables

## Prerequisites
- Modules 01–11 completed, especially Module 02 (nftables fundamentals)
- Comfort with the nft command-line tool
- Lab environment running (`~/firewalld-lab/start-lab.sh`)

---

## Learning Objectives
By the end of this module you will be able to:
1. Understand when and why to use direct rules versus firewalld abstractions
2. Use firewalld's `--direct` interface (legacy passthrough layer)
3. Write standalone nftables tables and chains that coexist with firewalld
4. Use nftables expressions: maps, verdict maps, sets, concatenations, and meters
5. Implement rate-limiting, connection tracking, and stateful rules directly in nftables
6. Use nftables flowtables for hardware-offloaded forwarding
7. Understand nftables priorities and how to hook at the right point
8. Manage nftables rules atomically with `nft -f`

---

## 12.1 — When to Go Below firewalld

firewalld covers the vast majority of real-world use cases. You should reach for direct nftables rules only when:

| Need | Reason to bypass firewalld |
|------|---------------------------|
| Per-packet rate limiting (meter) | firewalld rich rules support `--limit` but not meters |
| nftables flowtables (offload) | No firewalld abstraction exists |
| Verdict maps / routing by mark | Complex dispatch logic not expressible in zones |
| Table/chain hooks at custom priorities | firewalld owns priorities near 0; you need a different hook point |
| Atomic multi-rule transactions | firewalld applies rules one-at-a-time; `nft -f` is atomic |
| nftables sets with intervals | firewalld ipsets are limited to hash types |

---

## 12.2 — firewalld Direct Interface (Legacy)

The direct interface is firewalld's thin passthrough to the underlying packet filter. On RHEL 10 with the nftables backend, direct rules are injected into a special nftables chain.

> **Important**: The direct interface was designed for iptables compatibility. On RHEL 10 it maps to nftables using a compatibility shim. It still works, but is considered a **legacy mechanism**. Prefer standalone nftables tables (Section 12.3) for new rules.

### 12.2.1 Direct interface concepts

```
firewall-cmd --direct --add-rule <ipv> <table> <chain> <priority> <args>

  ipv       = ipv4 | ipv6 | eb (ebtables)
  table     = filter | mangle | nat | raw
  chain     = INPUT | OUTPUT | FORWARD | PREROUTING | POSTROUTING
              (or any custom chain you create)
  priority  = integer; lower runs first
  args      = iptables-syntax rule arguments
```

### 12.2.2 Direct rule examples

```bash
# Block a specific source IP at the INPUT chain (iptables syntax)
firewall-cmd --direct --add-rule ipv4 filter INPUT 0 \
    -s 10.0.0.5 -j DROP

# Rate-limit new SSH connections (iptables hashlimit module)
firewall-cmd --direct --add-rule ipv4 filter INPUT 0 \
    -p tcp --dport 22 -m state --state NEW \
    -m hashlimit --hashlimit-above 3/minute --hashlimit-burst 5 \
    --hashlimit-mode srcip --hashlimit-name ssh-ratelimit \
    -j DROP

# List all direct rules
firewall-cmd --direct --get-all-rules

# Remove a direct rule
firewall-cmd --direct --remove-rule ipv4 filter INPUT 0 \
    -s 10.0.0.5 -j DROP
```

### 12.2.3 Where direct rules appear in nftables

```bash
# After adding a direct rule, inspect nftables
nft list table ip firewalld_direct

# firewalld creates this table automatically when direct rules are added
# It contains chains named after the iptables chains you targeted
```

### 12.2.4 Direct rules are runtime-only by default

```bash
# Add permanently
firewall-cmd --permanent --direct --add-rule ipv4 filter INPUT 0 \
    -s 10.0.0.5 -j DROP

# Permanent direct rules are stored in:
cat /etc/firewalld/direct.xml
```

---

## 12.3 — Standalone nftables Tables

The cleanest approach for advanced rules on RHEL 10: create your own nftables table with a descriptive name, hook at the right priority, and leave firewalld's `firewalld` table untouched.

### 12.3.1 nftables hook priorities

nftables evaluates chains at their declared hook and priority. Lower numbers run first.

| Priority value | Symbolic name | Typical owner |
|---------------|--------------|--------------|
| -400 | `raw` | Connection tracking bypass |
| -300 | `mangle` | Packet marking |
| -200 | `dstnat` (prerouting) | DNAT/port forwarding |
| -100 | `filter` (prerouting) | Early filtering |
| 0 | *(default)* | Most filter rules |
| -1 | *(firewalld uses this)* | firewalld filter chains |
| 100 | `srcnat` (postrouting) | SNAT/masquerade |
| 300 | `mangle` (postrouting) | Post-routing marking |

> **firewalld reserves priority -1** for its `filter` chains on INPUT/OUTPUT/FORWARD.  
> Your custom filter chains at priority 0 run **after** firewalld.  
> If you want your rules to run **before** firewalld, use priority -2 or lower.

### 12.3.2 Creating a custom table

```bash
# Create a table for custom rate-limiting rules
nft add table inet custom_filter

# Add a chain that runs BEFORE firewalld (priority -2)
nft add chain inet custom_filter input_early \
    '{ type filter hook input priority -2; policy accept; }'
```

### 12.3.3 Writing to a file for atomic application

```bash
# /etc/nftables.d/custom-filter.nft
cat > /etc/nftables.d/custom-filter.nft << 'EOF'
#!/usr/sbin/nft -f

table inet custom_filter {

    # Sets for dynamic block lists
    set blocked_ips {
        type ipv4_addr
        flags dynamic, timeout
        timeout 1h
    }

    # Rate-limit new connections — 20/minute per source IP
    # Excess connections: add to blocked_ips and drop
    chain input_ratelimit {
        type filter hook input priority -2;

        # Already blocked? Drop immediately.
        ip saddr @blocked_ips drop

        # Rate-limit new TCP connections per source IP
        tcp flags syn \
            limit rate over 20/minute \
            add @blocked_ips { ip saddr timeout 10m } \
            drop

        accept
    }
}
EOF

# Apply atomically
nft -f /etc/nftables.d/custom-filter.nft

# Verify
nft list table inet custom_filter
```

### 12.3.4 Making custom tables persistent

On RHEL 10, `nftables.service` loads `/etc/sysconfig/nftables.conf` at boot.

```bash
# Option A: include your file from the main nftables config
echo 'include "/etc/nftables.d/custom-filter.nft"' >> /etc/sysconfig/nftables.conf

# Option B: use a separate systemd unit that runs after firewalld
cat > /etc/systemd/system/custom-nft-rules.service << 'EOF'
[Unit]
Description=Custom nftables rules
After=firewalld.service
Requires=firewalld.service

[Service]
Type=oneshot
ExecStart=/usr/sbin/nft -f /etc/nftables.d/custom-filter.nft
ExecStop=/usr/sbin/nft delete table inet custom_filter
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now custom-nft-rules
```

---

## 12.4 — Advanced nftables Expressions

### 12.4.1 Sets and named sets

```bash
# Static named set — list of trusted management IPs
nft add set inet custom_filter mgmt_hosts \
    '{ type ipv4_addr; elements = { 192.168.100.10, 192.168.100.11 }; }'

# Reference in a rule
nft add rule inet custom_filter input_ratelimit \
    ip saddr @mgmt_hosts accept

# Interval set — CIDR ranges
nft add set inet custom_filter trusted_nets \
    '{ type ipv4_addr; flags interval; elements = { 192.168.0.0/16, 10.0.0.0/8 }; }'
```

### 12.4.2 Verdict maps (vmaps)

Verdict maps dispatch packets to different verdicts based on a key — extremely efficient:

```bash
# Dispatch based on incoming interface → different policies
nft add map inet custom_filter iface_policy \
    '{ type ifname : verdict; }'

nft add element inet custom_filter iface_policy \
    '{ "eth0" : drop, "eth1" : accept, "eth2" : goto trusted_chain }'

# Use the map in a rule
nft add rule inet custom_filter input_ratelimit \
    iifname vmap @iface_policy
```

### 12.4.3 Concatenation sets (multi-key)

Match on multiple fields simultaneously in a single set lookup:

```bash
# Allow only specific (src IP, dest port) combinations
nft add set inet custom_filter allowed_combos \
    '{ type ipv4_addr . inet_service; flags interval; }'

nft add element inet custom_filter allowed_combos \
    '{ 10.0.0.0/8 . 22, 192.168.1.5 . 80, 192.168.1.5 . 443 }'

# Rule using the concatenation set
nft add rule inet custom_filter input_ratelimit \
    ip saddr . tcp dport @allowed_combos accept
```

### 12.4.4 Meters (per-element rate limiting)

Meters track state per-element (e.g., per source IP), without needing a named set:

```bash
# Rate-limit: max 100 new connections per minute per source IP
nft add rule inet custom_filter input_ratelimit \
    tcp flags syn \
    meter ssh_meter { ip saddr limit rate 100/minute } \
    accept

# Packets exceeding the meter rate are NOT accepted — they fall through
# Add a drop rule after:
nft add rule inet custom_filter input_ratelimit \
    tcp flags syn \
    meter ssh_drop { ip saddr limit rate over 100/minute } \
    drop
```

### 12.4.5 Packet marks and routing

```bash
# Mark packets from the DMZ for policy routing
nft add table inet custom_mangle

nft add chain inet custom_mangle preroute \
    '{ type route hook prerouting priority mangle; }'

nft add rule inet custom_mangle preroute \
    ip saddr 172.20.2.0/24 meta mark set 0x100

# Linux policy routing then routes marked packets differently:
ip rule add fwmark 0x100 table 200
ip route add default via 172.20.1.254 table 200
```

---

## 12.5 — nftables Flowtables (Fastpath Forwarding)

Flowtables offload established connection forwarding to the kernel's software fastpath (or hardware NIC), bypassing the full nftables ruleset for matched flows.

This dramatically increases forwarding throughput on routers/firewalls.

### 12.5.1 How flowtables work

```
New connection → full ruleset evaluation → accepted → added to flowtable
Subsequent packets → flowtable lookup → bypass full ruleset → forward directly
```

### 12.5.2 Creating a flowtable

```bash
cat > /etc/nftables.d/flowtable.nft << 'EOF'
table inet fastpath {

    flowtable ft {
        hook ingress priority filter;
        devices = { eth0, eth1, eth2 };
    }

    chain forward {
        type filter hook forward priority filter;

        # Offload established+related flows
        ip protocol { tcp, udp } flow offload @ft
    }
}
EOF

nft -f /etc/nftables.d/flowtable.nft
```

### 12.5.3 Verify flowtable entries

```bash
# Show flowtable flows
nft list flowtable inet fastpath ft

# Sample output:
# flowtable inet fastpath ft {
#     hook ingress priority 0;
#     devices = { eth0, eth1, eth2 };
# }
```

> **Note**: Flowtable offload bypasses connection tracking for offloaded packets, which means firewalld's state-based rules won't apply to subsequent packets in an offloaded flow. Use flowtables only after the firewall has accepted a connection.

---

## 12.6 — Atomic Rule Updates with `nft -f`

One of nftables' major advantages: atomic commits via a file.

### 12.6.1 The problem with incremental changes

```bash
# Each of these is a separate operation — non-atomic
nft add rule inet custom_filter input_ratelimit ip saddr 1.2.3.4 drop
nft add rule inet custom_filter input_ratelimit ip saddr 1.2.3.5 drop
# A packet from 1.2.3.5 could slip through between the two commands
```

### 12.6.2 Atomic replacement with a ruleset file

```bash
cat > /tmp/new-rules.nft << 'EOF'
# Flush and replace the entire table atomically
table inet custom_filter {
    set blocked_ips {
        type ipv4_addr
        flags interval
        elements = { 1.2.3.4, 1.2.3.5, 10.20.30.0/24 }
    }
    chain input_ratelimit {
        type filter hook input priority -2;
        ip saddr @blocked_ips drop
        accept
    }
}
EOF

# Apply atomically — either all rules apply or none
nft -f /tmp/new-rules.nft
```

### 12.6.3 Flush + reapply pattern

```bash
# Flush only your table, then reload — leaves firewalld's table untouched
nft flush table inet custom_filter
nft -f /etc/nftables.d/custom-filter.nft
```

### 12.6.4 Listing and saving current ruleset

```bash
# Save complete ruleset to file
nft list ruleset > /tmp/ruleset-backup.nft

# Save only your table
nft list table inet custom_filter > /tmp/custom-table.nft

# Restore
nft -f /tmp/ruleset-backup.nft
```

---

## 12.7 — Coexistence: firewalld + Custom nftables Tables

Key rules for safe coexistence:

| Rule | Reason |
|------|--------|
| Use a different table name (not `firewalld`) | firewalld owns and may flush the `firewalld` table |
| Use `inet` address family where possible | Covers both IPv4 and IPv6 |
| Pick priorities carefully (see 12.3.1) | Avoid conflicting with firewalld's -1 priority |
| Don't call `nft flush ruleset` | This also destroys firewalld's rules |
| Flush only your own table | `nft flush table inet custom_filter` |
| Use `nftables.service` or a systemd unit to restore on reboot | firewalld reloads its own rules; yours need separate persistence |

### Inspect both tables side by side

```bash
# firewalld's table
nft list table inet firewalld | head -30

# Your custom table
nft list table inet custom_filter
```

---

## 12.8 — Debugging nftables Rules

### 12.8.1 Rule counters

```bash
# Add a counter to a rule for visibility
nft add rule inet custom_filter input_ratelimit \
    ip saddr 10.0.0.0/8 counter accept

# View counts
nft list chain inet custom_filter input_ratelimit
# → ... counter packets 1042 bytes 61234 accept
```

### 12.8.2 Trace (revisit from Module 10, now applied to custom tables)

```bash
# Add trace to your chain
nft add rule inet custom_filter input_ratelimit \
    ip saddr 172.20.2.0/24 meta nftrace set 1

nft monitor trace
```

### 12.8.3 Common mistakes

| Mistake | Symptom | Fix |
|---------|---------|-----|
| Wrong hook type | Rules silently ignored | Verify `type filter hook input` syntax |
| Priority conflict with firewalld | Unexpected rule ordering | Use priority < -1 to run before firewalld |
| Flushed firewalld table | All firewall rules gone | Never `nft flush ruleset`; flush only your table |
| Inet family mismatch | IPv6 traffic not matched | Use `inet` not `ip` for dual-stack rules |
| Set not found on reload | Rules fail to apply | Ensure sets are defined before rules that reference them |

---

## Lab 12 — Direct Rules and Advanced nftables

**Objective**: Use firewalld direct interface, create a custom nftables table with rate-limiting, and verify coexistence with firewalld.

### Setup

```bash
~/firewalld-lab/start-lab.sh
podman exec -it node1 bash
```

---

### Step 1 — Add a direct rule (legacy)

```bash
# Block a specific IP using the direct interface
firewall-cmd --direct --add-rule ipv4 filter INPUT 0 \
    -s 172.20.2.99 -j DROP

# Verify it's in the ruleset
firewall-cmd --direct --get-all-rules
nft list table ip firewalld_direct
```

---

### Step 2 — Clean up the direct rule

```bash
firewall-cmd --direct --remove-rule ipv4 filter INPUT 0 \
    -s 172.20.2.99 -j DROP
```

---

### Step 3 — Create a custom nftables table with rate limiting

```bash
cat > /etc/nftables.d/lab-ratelimit.nft << 'EOF'
table inet lab_ratelimit {

    set burst_blocked {
        type ipv4_addr
        flags dynamic, timeout
        timeout 5m
        comment "IPs that exceeded connection rate"
    }

    chain input_guard {
        type filter hook input priority -2;

        # Allow already-established connections through immediately
        ct state established,related accept

        # Drop sources that already hit the rate limit
        ip saddr @burst_blocked drop

        # Block IPs that send >10 new TCP SYNs per second
        tcp flags & (fin|syn|rst|ack) == syn \
            meter syn_meter { ip saddr limit rate over 10/second } \
            add @burst_blocked { ip saddr } \
            drop

        accept
    }
}
EOF

nft -f /etc/nftables.d/lab-ratelimit.nft
nft list table inet lab_ratelimit
```

---

### Step 4 — Verify coexistence with firewalld

```bash
# firewalld's table still intact?
nft list table inet firewalld | grep "chain filter_INPUT" | head -3

# Your table present?
nft list table inet lab_ratelimit | head -5

# Both tables in ruleset?
nft list ruleset | grep "^table"
```

---

### Step 5 — Test rate limiting (SYN flood simulation)

```bash
# From node2 (DMZ), generate rapid connection attempts to node1
podman exec -it node2 bash

# Install hping3 or use a simple bash loop
for i in $(seq 1 20); do
    curl --connect-timeout 1 http://172.20.1.10:80 2>/dev/null &
done
wait
exit   # back to node1
```

```bash
# On node1 — check if any IPs got added to burst_blocked
nft list set inet lab_ratelimit burst_blocked
```

---

### Step 6 — Create a verdict map

```bash
# Add a map to dispatch by interface
nft add map inet lab_ratelimit iface_action \
    '{ type ifname : verdict; }'

# Populate the map
nft add element inet lab_ratelimit iface_action \
    '{ "lo" : accept }'

# Add a rule to use the map (before the rate-limit logic)
nft insert rule inet lab_ratelimit input_guard \
    iifname vmap @iface_action

# Verify
nft list table inet lab_ratelimit
```

---

### Step 7 — Atomic update of the blocked set

```bash
# Atomically replace the blocked_ips set elements
nft flush set inet lab_ratelimit burst_blocked
nft add element inet lab_ratelimit burst_blocked \
    '{ 172.20.2.50, 172.20.2.51 }'

nft list set inet lab_ratelimit burst_blocked
```

---

### Step 8 — Make custom table persistent

```bash
# Save current state
nft list table inet lab_ratelimit > /etc/nftables.d/lab-ratelimit.nft

# Create systemd unit
cat > /etc/systemd/system/lab-nft-rules.service << 'EOF'
[Unit]
Description=Lab custom nftables rules
After=firewalld.service
PartOf=firewalld.service

[Service]
Type=oneshot
ExecStart=/usr/sbin/nft -f /etc/nftables.d/lab-ratelimit.nft
ExecReload=/usr/sbin/nft -f /etc/nftables.d/lab-ratelimit.nft
ExecStop=/usr/sbin/nft delete table inet lab_ratelimit
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now lab-nft-rules
```

---

### Step 9 — Cleanup

```bash
systemctl disable --now lab-nft-rules
nft delete table inet lab_ratelimit 2>/dev/null || true
rm -f /etc/nftables.d/lab-ratelimit.nft
rm -f /etc/systemd/system/lab-nft-rules.service
systemctl daemon-reload
```

---

### Lab Verification Checklist

- [ ] `nft list table ip firewalld_direct` showed the direct rule before removal
- [ ] `nft list ruleset | grep "^table"` shows both `firewalld` and `lab_ratelimit` tables
- [ ] Rate-limiting chain at priority -2 runs before firewalld's chains
- [ ] Verdict map dispatches loopback traffic to `accept`
- [ ] Burst IPs appear in `burst_blocked` set after flood test
- [ ] systemd unit loads the custom table after firewalld on simulated reboot

---

## Key Takeaways

| Topic | Key Point |
|-------|-----------|
| Direct interface | Legacy iptables passthrough; works but deprecated; prefer standalone tables |
| Custom nftables tables | Use a unique name; never touch the `firewalld` table |
| Hook priority | firewalld uses -1; use -2 or lower to run before it |
| Verdict maps | O(1) dispatch on key — replace long if/else chains |
| Meters | Per-element rate tracking without needing a named set |
| Atomic updates | `nft -f <file>` is transactional; incremental `nft add rule` is not |
| Persistence | Requires a separate systemd unit or inclusion in `/etc/sysconfig/nftables.conf` |
| Coexistence safety | Only `flush table inet <your_table>` — never `flush ruleset` |

---

*Next: [Module 13 — Capstone Project](13-capstone-project.md)*

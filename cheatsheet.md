# firewalld + nftables Cheatsheet
[![CC BY-NC-SA 4.0](https://img.shields.io/badge/License-CC%20BY--NC--SA%204.0-lightgrey)](./LICENSE.md)
[![RHEL 10](https://img.shields.io/badge/platform-RHEL%2010-red)](https://access.redhat.com/products/red-hat-enterprise-linux)
[![firewalld](https://img.shields.io/badge/firewalld-RHEL%2010-orange)](https://access.redhat.com/products/red-hat-enterprise-linux)

### RHEL 10 | firewalld 2.x | nftables backend

---

## Table of Contents

1. [Quick Status](#quick-status)
2. [Zones](#zones)
3. [Services](#services)
4. [Ports and Protocols](#ports-and-protocols)
5. [ICMP](#icmp)
6. [Rich Rules](#rich-rules)
7. [NAT — Masquerade and Port Forwarding](#nat-masquerade-and-port-forwarding)
8. [Policies (Inter-Zone Forwarding)](#policies-inter-zone-forwarding)
9. [IP Sets](#ip-sets)
10. [Logging](#logging)
11. [Runtime vs Permanent](#runtime-vs-permanent)
12. [Lockdown Mode](#lockdown-mode)
13. [Panic Mode](#panic-mode)
14. [nftables Quick Reference](#nftables-quick-reference)
15. [nftables Chain Hooks (firewalld table)](#nftables-chain-hooks-firewalld-table)
16. [nftables Priority Reference](#nftables-priority-reference)
17. [Correlation: firewall-cmd → nftables](#correlation-firewall-cmd-nftables)
18. [Troubleshooting Quick Checklist](#troubleshooting-quick-checklist)
19. [File Locations](#file-locations)
20. [Service Management](#service-management)

---

↑ [Back to TOC](#table-of-contents)

## Quick Status

```bash
firewall-cmd --state                    # Is firewalld running?
firewall-cmd --get-default-zone         # Default zone name
firewall-cmd --get-active-zones         # Active zones + their interfaces/sources
firewall-cmd --list-all                 # Everything in default zone
firewall-cmd --list-all --zone=public   # Everything in a specific zone
firewall-cmd --list-all-zones           # Everything in all zones
systemctl status firewalld              # systemd service status
```

---

↑ [Back to TOC](#table-of-contents)

## Zones

```bash
# List
firewall-cmd --get-zones                          # All zone names
firewall-cmd --get-default-zone                   # Current default
firewall-cmd --get-zone-of-interface=eth0         # Zone for an interface

# Set default zone
firewall-cmd --set-default-zone=public

# Create / delete custom zone
firewall-cmd --new-zone=myzone --permanent
firewall-cmd --delete-zone=myzone --permanent

# Assign interfaces
firewall-cmd --zone=internal --add-interface=eth1 --permanent
firewall-cmd --zone=internal --remove-interface=eth1 --permanent

# Assign source IPs/subnets (source-based zone)
firewall-cmd --zone=mgmt --add-source=192.168.100.0/24 --permanent
firewall-cmd --zone=mgmt --remove-source=192.168.100.0/24 --permanent

# Zone target (what happens to unmatched packets)
firewall-cmd --zone=external --set-target=DROP --permanent    # drop silently
firewall-cmd --zone=external --set-target=REJECT --permanent  # reject with ICMP
firewall-cmd --zone=trusted  --set-target=ACCEPT --permanent  # accept all
firewall-cmd --zone=public   --set-target=default --permanent # default REJECT

# Get zone target
firewall-cmd --zone=external --get-target
```

---

↑ [Back to TOC](#table-of-contents)

## Services

```bash
# List available service definitions
firewall-cmd --get-services

# Add / remove service in zone
firewall-cmd --zone=public --add-service=http --permanent
firewall-cmd --zone=public --remove-service=http --permanent

# Query if service is present
firewall-cmd --zone=public --query-service=http

# Show service definition (ports it opens)
firewall-cmd --info-service=http

# List services active in a zone (runtime)
firewall-cmd --zone=public --list-services

# Create custom service
cat > /etc/firewalld/services/myapp.xml << 'EOF'
<?xml version="1.0" encoding="utf-8"?>
<service>
  <short>MyApp</short>
  <description>My custom application</description>
  <port protocol="tcp" port="8080"/>
  <port protocol="tcp" port="8443"/>
</service>
EOF
firewall-cmd --reload
firewall-cmd --zone=public --add-service=myapp --permanent
```

---

↑ [Back to TOC](#table-of-contents)

## Ports and Protocols

```bash
# Add / remove individual ports
firewall-cmd --zone=public --add-port=8080/tcp --permanent
firewall-cmd --zone=public --add-port=5000-5100/udp --permanent
firewall-cmd --zone=public --remove-port=8080/tcp --permanent

# List open ports
firewall-cmd --zone=public --list-ports

# Add protocol (not port-based, e.g., GRE, OSPF)
firewall-cmd --zone=trusted --add-protocol=gre --permanent
firewall-cmd --zone=trusted --remove-protocol=gre --permanent
```

---

↑ [Back to TOC](#table-of-contents)

## ICMP

```bash
# List available ICMP types
firewall-cmd --get-icmptypes

# Block / unblock ICMP type
firewall-cmd --zone=external --add-icmp-block=echo-request --permanent
firewall-cmd --zone=external --remove-icmp-block=echo-request --permanent

# List blocked ICMP types
firewall-cmd --zone=external --list-icmp-blocks

# Invert ICMP blocks (block ALL except listed)
firewall-cmd --zone=external --add-icmp-block-inversion --permanent
```

---

↑ [Back to TOC](#table-of-contents)

## Rich Rules

```bash
# Syntax template:
# rule [family="ipv4|ipv6"]
#      [source address="IP/CIDR" [invert="true"]]
#      [destination address="IP/CIDR"]
#      [service name="svc" | port port="P" protocol="tcp|udp" | protocol value="P"]
#      [log [prefix="..."] [level="info|warn|..."] [limit value="R/unit"]]
#      [audit]
#      [accept | drop | reject [type="..."] | mark set="..."]

# Allow source IP
firewall-cmd --zone=public --add-rich-rule='
  rule family="ipv4" source address="10.0.0.5" service name="ssh" accept' --permanent

# Block source subnet
firewall-cmd --zone=public --add-rich-rule='
  rule family="ipv4" source address="192.168.99.0/24" drop' --permanent

# Rate-limit SSH (3 connections per minute, then reject)
firewall-cmd --zone=public --add-rich-rule='
  rule family="ipv4"
  service name="ssh"
  limit value="3/m" accept' --permanent

# Log and drop
firewall-cmd --zone=external --add-rich-rule='
  rule family="ipv4"
  source address="203.0.113.0/24"
  log prefix="BLOCKED: " level="info"
  drop' --permanent

# List / remove rich rules
firewall-cmd --zone=public --list-rich-rules
firewall-cmd --zone=public --remove-rich-rule='rule family="ipv4" source address="10.0.0.5" service name="ssh" accept' --permanent
```

---

↑ [Back to TOC](#table-of-contents)

## NAT — Masquerade and Port Forwarding

```bash
# Enable / disable masquerade (SNAT for outbound)
firewall-cmd --zone=external --add-masquerade --permanent
firewall-cmd --zone=external --remove-masquerade --permanent
firewall-cmd --zone=external --query-masquerade

# Port forward (DNAT)
# Format: --add-forward-port=port=<SRC>:proto=<P>:toport=<DST>[:toaddr=<IP>]

# Forward local port 8443 → local port 443
firewall-cmd --zone=external --add-forward-port=port=8443:proto=tcp:toport=443 --permanent

# Forward local port 443 → remote host 192.168.1.10:8443
firewall-cmd --zone=external --add-forward-port=port=443:proto=tcp:toport=8443:toaddr=192.168.1.10 --permanent

# List forward ports
firewall-cmd --zone=external --list-forward-ports

# Remove
firewall-cmd --zone=external --remove-forward-port=port=443:proto=tcp:toport=8443:toaddr=192.168.1.10 --permanent
```

---

↑ [Back to TOC](#table-of-contents)

## Policies (Inter-Zone Forwarding)

```bash
# Create / delete policy
firewall-cmd --new-policy=dmz-to-ext --permanent
firewall-cmd --delete-policy=dmz-to-ext --permanent

# Set ingress/egress zones
firewall-cmd --policy=dmz-to-ext --add-ingress-zone=dmz --permanent
firewall-cmd --policy=dmz-to-ext --add-egress-zone=external --permanent

# Set policy target
firewall-cmd --policy=dmz-to-ext --set-target=ACCEPT --permanent
firewall-cmd --policy=dmz-to-ext --set-target=DROP --permanent

# Add services / ports to policy (same syntax as zones)
firewall-cmd --policy=dmz-to-ext --add-service=http --permanent

# List policies
firewall-cmd --list-all-policies
firewall-cmd --policy=dmz-to-ext --list-all

# Special zone values for policies
# HOST = the firewalld host itself
# ANY  = any zone
firewall-cmd --policy=fw-outbound --add-ingress-zone=HOST --permanent
firewall-cmd --policy=fw-outbound --add-egress-zone=ANY --permanent
```

---

↑ [Back to TOC](#table-of-contents)

## IP Sets

```bash
# Create ipset
firewall-cmd --new-ipset=blocklist --type=hash:ip --permanent
firewall-cmd --new-ipset=net-blocklist --type=hash:net --permanent

# Add / remove entries
firewall-cmd --ipset=blocklist --add-entry=1.2.3.4 --permanent
firewall-cmd --ipset=blocklist --remove-entry=1.2.3.4 --permanent

# Bulk load from file
firewall-cmd --ipset=blocklist --add-entries-from-file=/tmp/ips.txt --permanent

# Use ipset in a zone (as source)
firewall-cmd --zone=drop --add-source=ipset:blocklist --permanent

# Use ipset in a rich rule
firewall-cmd --zone=public --add-rich-rule='
  rule source ipset="blocklist" drop' --permanent

# List ipset entries
firewall-cmd --ipset=blocklist --get-entries

# List all ipsets
firewall-cmd --get-ipsets
firewall-cmd --info-ipset=blocklist
```

---

↑ [Back to TOC](#table-of-contents)

## Logging

```bash
# Enable/disable LogDenied
firewall-cmd --set-log-denied=all        # log all denied unicast+broadcast+multicast
firewall-cmd --set-log-denied=unicast    # log denied unicast only
firewall-cmd --set-log-denied=off        # disable (default)
firewall-cmd --get-log-denied            # check current value

# Read denied packet logs
journalctl -k --grep="filter_IN" -f
journalctl -k --grep="filter_FWD" --since="10 minutes ago"

# Daemon debug logging
firewall-cmd --debug=2                   # 0=off, 1, 2, 3=verbose
journalctl -u firewalld -f
```

---

↑ [Back to TOC](#table-of-contents)

## Runtime vs Permanent

```bash
# Apply a runtime change AND make it permanent:
firewall-cmd --zone=public --add-service=http           # runtime only
firewall-cmd --zone=public --add-service=http --permanent  # permanent only (not active until reload)
firewall-cmd --reload                                    # apply permanent → runtime

# Do both in one shot:
firewall-cmd --zone=public --add-service=http
firewall-cmd --zone=public --add-service=http --permanent

# Promote all current runtime rules to permanent:
firewall-cmd --runtime-to-permanent

# Check for divergence:
diff <(firewall-cmd --zone=public --list-all) \
     <(firewall-cmd --zone=public --list-all --permanent)

# Reload and complete-reload
firewall-cmd --reload             # apply permanent; keeps established connections
firewall-cmd --complete-reload    # restart nftables ruleset; DROPS established connections

# Validate permanent config
firewall-cmd --check-config
```

---

↑ [Back to TOC](#table-of-contents)

## Lockdown Mode

```bash
# Enable / disable
firewall-cmd --lockdown-on
firewall-cmd --lockdown-off
firewall-cmd --query-lockdown

# Manage whitelist
firewall-cmd --add-lockdown-whitelist-command='/usr/bin/python3 -s /usr/bin/firewall-cmd*'
firewall-cmd --add-lockdown-whitelist-uid=0
firewall-cmd --add-lockdown-whitelist-user=netadmin
firewall-cmd --add-lockdown-whitelist-context='system_u:system_r:NetworkManager_t:s0'

firewall-cmd --list-lockdown-whitelist-commands
firewall-cmd --list-lockdown-whitelist-uids
firewall-cmd --list-lockdown-whitelist-users
firewall-cmd --list-lockdown-whitelist-contexts
```

---

↑ [Back to TOC](#table-of-contents)

## Panic Mode

```bash
# Block ALL traffic (emergency — including SSH!)
firewall-cmd --panic-on

# Restore normal operation
firewall-cmd --panic-off

# Check panic status
firewall-cmd --query-panic
```

---

↑ [Back to TOC](#table-of-contents)

## nftables Quick Reference

```bash
# List full ruleset
nft list ruleset

# List a specific table
nft list table inet firewalld

# List a specific chain
nft list chain inet firewalld filter_INPUT
nft list chain inet firewalld filter_IN_public_allow

# List with rule handles (needed to delete by handle)
nft --handle list chain inet firewalld filter_INPUT

# Delete a rule by handle
nft delete rule inet firewalld filter_INPUT handle 42

# Add a rule to a specific chain
nft add rule inet firewalld filter_INPUT \
    ip saddr 10.0.0.5 tcp dport 22 accept

# Count packets matching a rule
nft add rule inet mychain myinput counter accept

# Watch trace (after adding nftrace set 1 to a rule)
nft monitor trace

# Flush only your own table (NEVER flush ruleset — destroys firewalld rules)
nft flush table inet my_custom_table

# Apply rules atomically from file
nft -f /etc/nftables.d/my-rules.nft

# Save current ruleset
nft list ruleset > /tmp/backup.nft
```

---

↑ [Back to TOC](#table-of-contents)

## nftables Chain Hooks (firewalld table)

| Chain | Hook | What it does |
|-------|------|-------------|
| `filter_INPUT` | input | Governs traffic destined for this host |
| `filter_OUTPUT` | output | Governs traffic originating from this host |
| `filter_FORWARD` | forward | Governs traffic being routed through this host |
| `filter_IN_ZONES` | — | Dispatches to per-zone input chains |
| `filter_IN_<zone>` | — | Per-zone input rules |
| `filter_IN_<zone>_allow` | — | Allow rules for the zone |
| `filter_IN_<zone>_deny` | — | Deny/log rules for the zone |
| `nat_PRE_<zone>` | prerouting | DNAT rules for the zone |
| `nat_POST_<zone>` | postrouting | SNAT/masquerade rules for the zone |
| `filter_FWD_<policy>` | — | Per-policy forward rules |

---

↑ [Back to TOC](#table-of-contents)

## nftables Priority Reference

| Priority | Constant | Typical use |
|---------|----------|------------|
| -400 | raw | Connection tracking bypass |
| -300 | mangle | Packet marking (prerouting) |
| -200 | dstnat | DNAT (prerouting) |
| **-1** | — | **firewalld filter chains** |
| 0 | filter | Default — runs after firewalld |
| 100 | srcnat | SNAT/masquerade (postrouting) |

> **Use priority -2 or lower** to run custom rules before firewalld.

---

↑ [Back to TOC](#table-of-contents)

## Correlation: firewall-cmd → nftables

| firewall-cmd | nftables effect |
|-------------|----------------|
| `--zone=Z --add-service=http` | Adds `tcp dport 80 accept` to `filter_IN_Z_allow` |
| `--zone=Z --set-target=DROP` | Adds `drop` to `filter_IN_Z` |
| `--zone=Z --add-masquerade` | Adds `masquerade` to `nat_POST_Z` |
| `--zone=Z --add-forward-port=port=443:...` | Adds DNAT to `nat_PRE_Z` |
| `--zone=Z --add-rich-rule='... log ...'` | Adds `log prefix` to `filter_IN_Z_allow` or `_deny` |
| `--set-log-denied=all` | Adds `log` statement to `filter_IN_Z_deny` chains |
| `--new-ipset=X --type=hash:ip` | Creates `set X { type ipv4_addr; }` in nftables |

---

↑ [Back to TOC](#table-of-contents)

## Troubleshooting Quick Checklist

```
1. Does the packet reach the host?          → tcpdump / nft monitor
2. Which interface/zone?                    → --get-active-zones / --get-zone-of-interface
3. Which chain evaluates it?                → nft list chain ... filter_IN_ZONES
4. What verdict?                            → nft monitor trace / --list-all
5. Forward traffic: routing + egress zone?  → sysctl ip_forward / --query-masquerade
```

```bash
# One-liner status summary
echo "=== Zones ===" && firewall-cmd --get-active-zones
echo "=== Default ===" && firewall-cmd --get-default-zone
echo "=== LogDenied ===" && firewall-cmd --get-log-denied
echo "=== Lockdown ===" && firewall-cmd --query-lockdown
echo "=== Panic ===" && firewall-cmd --query-panic
echo "=== nft tables ===" && nft list ruleset | grep "^table"
```

---

↑ [Back to TOC](#table-of-contents)

## File Locations

| Path | Purpose |
|------|---------|
| `/etc/firewalld/firewalld.conf` | Main daemon config (Lockdown, LogDenied, etc.) |
| `/etc/firewalld/zones/` | Custom zone XML overrides |
| `/etc/firewalld/services/` | Custom service definitions |
| `/etc/firewalld/policies/` | Custom policy definitions |
| `/etc/firewalld/ipsets/` | Persistent ipset definitions |
| `/etc/firewalld/direct.xml` | Permanent direct rules |
| `/etc/firewalld/lockdown-whitelist.xml` | Lockdown whitelist |
| `/usr/lib/firewalld/zones/` | Shipped zone defaults (do not edit) |
| `/usr/lib/firewalld/services/` | Shipped service definitions (do not edit) |
| `/etc/sysconfig/nftables.conf` | nftables service config (loaded at boot) |
| `/etc/nftables.d/` | Drop-in nftables rule files |

---

↑ [Back to TOC](#table-of-contents)

## Service Management

```bash
systemctl enable --now firewalld      # Enable + start
systemctl disable --now firewalld     # Disable + stop
systemctl restart firewalld           # Full restart (drops established connections)
systemctl reload firewalld            # Reload config (equivalent to --complete-reload)
```

---

*Full course: [README.md](README.md) | FAQ: [faq.md](faq.md)*

---

© 2026 UncleJS — Licensed under CC BY-NC-SA 4.0

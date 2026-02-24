# firewalld FAQ
### RHEL 10 | firewalld 2.x | nftables backend
### 75 Questions and Answers

---

## Part 1 — Concepts and Architecture

**Q1. What is firewalld and how does it relate to nftables?**

firewalld is a dynamic firewall management daemon that provides a high-level abstraction layer for configuring packet filtering. On RHEL 10, firewalld uses nftables as its backend: every `firewall-cmd` operation translates into one or more nftables rules inside the `firewalld` table. You can inspect those rules directly with `nft list ruleset`.

---

**Q2. What happened to iptables on RHEL 10?**

iptables has been removed from RHEL 10. The kernel no longer includes the `iptables` netfilter subsystem modules (x_tables). nftables is the only packet filtering framework. Any iptables rules from RHEL 9 or older systems must be migrated to either firewalld abstractions or native nftables rules.

---

**Q3. Does firewalld still work if I write nftables rules directly?**

Yes, with caveats. firewalld owns the `inet firewalld` table. You should create your own table (e.g., `inet custom_rules`) for direct nftables rules. Never `nft flush ruleset` — that destroys firewalld's chains. See Module 12 for the coexistence pattern.

---

**Q4. What is the difference between a zone and a policy?**

A **zone** governs traffic arriving at or destined for a specific interface or source address. A **policy** governs traffic being forwarded between zones (ingress zone → egress zone). Policies were introduced to replace the older `--direct` forward rules and rich-rule forwarding workarounds.

---

**Q5. What does "runtime vs permanent" mean?**

- **Runtime**: the currently active configuration, stored in memory. Changed by `firewall-cmd` without `--permanent`. Lost on `--reload` or restart.
- **Permanent**: stored in XML files under `/etc/firewalld/`. Applied to runtime after `firewall-cmd --reload`. Changes made with `--permanent` are NOT active until a reload.

Always do both: set `--permanent` and then `--reload`, or set runtime first and then promote with `--runtime-to-permanent`.

---

**Q6. What is the default zone and why does it matter?**

The default zone is applied to any interface that is not explicitly assigned to a zone. If a new network interface appears (e.g., a USB tethering device) it will be placed in the default zone automatically. Ensure the default zone is appropriately restrictive. The factory default is `public`.

---

**Q7. Can a single packet match multiple zones?**

No. A packet enters through one interface and is dispatched to exactly one zone. The priority order is:
1. Source address (most specific — source-based zones win)
2. Interface assignment
3. Default zone (fallback)

---

**Q8. What are zone targets and what values are available?**

Zone targets define what happens to packets that don't match any specific rule in the zone:

| Target | Behavior |
|--------|----------|
| `default` | REJECT with ICMP admin-prohibited |
| `ACCEPT` | Accept all traffic |
| `DROP` | Silently discard |
| `REJECT` | Same as default, explicit |

---

**Q9. What is the difference between DROP and REJECT?**

`DROP` silently discards packets with no response. `REJECT` sends an ICMP error back to the sender. `DROP` is stealthier (the sender doesn't know the host exists) but causes slower timeouts for legitimate clients. `REJECT` is more RFC-compliant and makes debugging easier.

---

**Q10. What is panic mode?**

`firewall-cmd --panic-on` blocks ALL network traffic immediately — inbound and outbound. It is a last resort for security incidents. It will disconnect SSH sessions. Use `podman exec` or console access to recover with `firewall-cmd --panic-off`.

---

## Part 2 — Zones and Interfaces

**Q11. How do I find which zone an interface belongs to?**

```bash
firewall-cmd --get-zone-of-interface=eth0
```

Or see all active zones and their members:
```bash
firewall-cmd --get-active-zones
```

---

**Q12. How do I assign an interface to a zone permanently?**

```bash
firewall-cmd --zone=internal --add-interface=eth1 --permanent
firewall-cmd --reload
```

---

**Q13. Can an interface be in multiple zones at the same time?**

No. An interface can only be in one zone at a time. However, you can use source-based zones to apply different rules based on source IP, so traffic arriving on the same interface from different subnets can be handled by different zones.

---

**Q14. What is a source-based zone and when should I use it?**

A source-based zone matches on the packet's source IP address rather than on which interface it arrived. Use it when you have management traffic and production traffic arriving on the same interface but from different subnets:

```bash
firewall-cmd --zone=mgmt --add-source=192.168.100.0/24 --permanent
```

Traffic from 192.168.100.0/24 gets the `mgmt` zone rules. All other traffic on the same interface gets the interface's zone rules.

---

**Q15. What happens if a source IP matches a source-based zone AND the interface is in another zone?**

The **source-based zone takes priority**. Source matching is evaluated before interface matching in the `filter_IN_ZONES` dispatch chain.

---

**Q16. How do I remove an interface from a zone?**

```bash
firewall-cmd --zone=internal --remove-interface=eth1 --permanent
firewall-cmd --reload
```

The interface then falls back to the default zone.

---

**Q17. How do I see what zone will handle a packet from a specific source IP?**

Check what source-based zones are active:
```bash
firewall-cmd --get-active-zones
```
Look for any zone that lists your source IP or subnet under "sources". If none match, the interface's zone handles it.

---

**Q18. Why does `--get-active-zones` not show all zones?**

Only zones with at least one active interface or source assignment are "active." A zone can exist but be inactive (no traffic routes to it). Use `--get-zones` to see all defined zones regardless of activity.

---

## Part 3 — Services, Ports, and Protocols

**Q19. What is a service in firewalld?**

A service is a named collection of ports, protocols, and optional destination addresses. It's defined in an XML file. Using service names makes rules human-readable and maintainable. Example: `http` opens TCP port 80; `https` opens TCP 443.

---

**Q20. Where are service definitions stored?**

- Shipped definitions: `/usr/lib/firewalld/services/` (do not edit these)
- Custom definitions: `/etc/firewalld/services/` (create or override here)

---

**Q21. How do I create a custom service?**

```bash
cat > /etc/firewalld/services/myapp.xml << 'EOF'
<?xml version="1.0" encoding="utf-8"?>
<service>
  <short>MyApp</short>
  <port protocol="tcp" port="8080"/>
</service>
EOF
firewall-cmd --reload
firewall-cmd --zone=public --add-service=myapp --permanent
```

---

**Q22. How do I open a port range?**

```bash
firewall-cmd --zone=public --add-port=5000-5100/tcp --permanent
```

---

**Q23. What is the difference between adding a service and adding a port?**

Services are named groupings (e.g., `http` for port 80). Ports are direct numeric opens. Use services for well-known applications — it's self-documenting. Use port numbers when there's no standard service definition or for custom apps.

---

**Q24. How do I open a non-TCP/UDP protocol like GRE or OSPF?**

```bash
firewall-cmd --zone=trusted --add-protocol=gre --permanent
firewall-cmd --zone=trusted --add-protocol=ospf --permanent
```

Protocol names are from `/etc/protocols`.

---

## Part 4 — Rich Rules

**Q25. When should I use a rich rule instead of a service/port rule?**

Use rich rules when you need to combine conditions:
- Allow a service only from a specific source IP
- Rate-limit connections
- Log traffic that matches specific criteria
- Apply rules to specific destinations
- Use audit logging per rule

Simple port/service rules can't do any of these.

---

**Q26. What is the rich rule syntax?**

```
rule [family="ipv4|ipv6"]
     [source address="IP/CIDR" [invert="true"]]
     [destination address="IP/CIDR"]
     [service name="svc" | port port="P" protocol="proto" | protocol value="P" | icmp-type name="T"]
     [log [prefix="text"] [level="emerg|alert|crit|err|warning|notice|info|debug"] [limit value="N/unit"]]
     [audit [type="accept|drop|reject"]]
     [accept | drop | reject [type="icmp-type"]]
```

---

**Q27. How do I block a specific IP address with a rich rule?**

```bash
firewall-cmd --zone=public --add-rich-rule='
  rule family="ipv4" source address="1.2.3.4" drop' --permanent
```

---

**Q28. How do I allow SSH from one specific IP and block it from everyone else?**

```bash
# Allow SSH from 10.0.0.5 only
firewall-cmd --zone=public --add-rich-rule='
  rule family="ipv4" source address="10.0.0.5" service name="ssh" accept' --permanent

# Remove SSH from the zone's general allows
firewall-cmd --zone=public --remove-service=ssh --permanent

firewall-cmd --reload
```

---

**Q29. How do I rate-limit connections with a rich rule?**

```bash
# Allow max 5 new SSH connections per minute per source IP
firewall-cmd --zone=public --add-rich-rule='
  rule family="ipv4"
  service name="ssh"
  limit value="5/m"
  accept' --permanent
```

The `limit` in a rich rule applies to the entire rule, not per-source. For per-source rate limiting, use a custom nftables meter (Module 12).

---

**Q30. Can rich rules log and accept/drop in the same rule?**

Yes:
```bash
firewall-cmd --zone=public --add-rich-rule='
  rule family="ipv4"
  source address="10.0.0.0/8"
  service name="http"
  log prefix="HTTP-INTERNAL: " level="info"
  accept' --permanent
```

---

**Q31. How do I use `invert` in a rich rule source?**

```bash
# Block all traffic EXCEPT from 10.0.0.0/8
firewall-cmd --zone=public --add-rich-rule='
  rule family="ipv4" source address="10.0.0.0/8" invert="true" drop' --permanent
```

---

**Q32. How do I remove a rich rule?**

Use `--remove-rich-rule` with the exact same rule string as you used to add it:

```bash
firewall-cmd --zone=public --remove-rich-rule='
  rule family="ipv4" source address="1.2.3.4" drop' --permanent
```

Alternatively, list rules with `--list-rich-rules`, copy the exact string, and use it in `--remove-rich-rule`.

---

## Part 5 — NAT, Masquerade, and Port Forwarding

**Q33. What is masquerade and when do I need it?**

Masquerade is a form of SNAT (source NAT) where outgoing packets have their source IP replaced with the firewall's egress interface IP. Use it when hosts in internal/DMZ zones need internet access but don't have public IPs. The external zone is the typical place to enable it.

---

**Q34. How do I enable masquerade?**

```bash
firewall-cmd --zone=external --add-masquerade --permanent
firewall-cmd --reload
```

Also ensure `net.ipv4.ip_forward=1` is set in `/etc/sysctl.d/`.

---

**Q35. How do I forward external port 443 to an internal server?**

```bash
# Forward external TCP 443 → internal server 192.168.1.10 port 443
firewall-cmd --zone=external --add-forward-port=\
port=443:proto=tcp:toport=443:toaddr=192.168.1.10 --permanent

firewall-cmd --reload
```

---

**Q36. What is the difference between port forwarding and a DNAT policy?**

`--add-forward-port` is firewalld's built-in DNAT mechanism. It modifies the PREROUTING chain. A DNAT policy or rich rule achieves the same effect through the policy framework (Module 05) or direct nftables rules (Module 12). For simple cases, `--add-forward-port` is the right choice.

---

**Q37. Do I need both masquerade and a forward port for traffic to flow to an internal server?**

Yes (in most cases). Port forwarding (DNAT) changes the destination IP. Masquerade ensures that return traffic is routed back through the firewall. Without masquerade, the internal server might try to reply directly to the external client (bypassing the firewall) and the connection would fail.

---

**Q38. How do I forward a port on the same machine to a different local port?**

```bash
# Forward local port 8080 → local port 80 (no toaddr needed)
firewall-cmd --zone=external --add-forward-port=port=8080:proto=tcp:toport=80 --permanent
```

---

## Part 6 — Policies

**Q39. What is a firewalld policy (introduced in firewalld 0.9)?**

A policy is a set of rules that applies to traffic flowing between two zones (ingress zone → egress zone). It allows you to control forwarding at a granular level — for example, allowing HTTP from the DMZ zone to the external zone but nothing else.

---

**Q40. How do I allow all forwarding from DMZ to external?**

```bash
firewall-cmd --new-policy=dmz-to-ext --permanent
firewall-cmd --policy=dmz-to-ext --add-ingress-zone=dmz --permanent
firewall-cmd --policy=dmz-to-ext --add-egress-zone=external --permanent
firewall-cmd --policy=dmz-to-ext --set-target=ACCEPT --permanent
firewall-cmd --reload
```

---

**Q41. What are the special zone values HOST and ANY in policies?**

- `HOST`: represents the firewalld host itself (rules for traffic originating from or destined to the host)
- `ANY`: matches any zone

Example — control outbound traffic from the firewall host itself:
```bash
firewall-cmd --policy=host-out --add-ingress-zone=HOST --permanent
firewall-cmd --policy=host-out --add-egress-zone=ANY --permanent
```

---

**Q42. Can I add services to a policy, or only set a target?**

You can add services, ports, rich rules, and more to a policy — just like zones. If you set `--set-target=CONTINUE` the policy can add specific allows while falling through to the next policy.

---

## Part 7 — IP Sets

**Q43. What is an IP set and when should I use one?**

An IP set is a kernel-level hash table of IP addresses, subnets, or port combinations. It evaluates in O(1) regardless of size. Use an IP set instead of individual rich rules when you have more than ~20 addresses to match. Sets support dynamic addition/removal without recreating rules.

---

**Q44. What ipset types are available in firewalld?**

Common types (backed by nftables sets):
- `hash:ip` — individual IPv4 addresses
- `hash:ip6` — individual IPv6 addresses
- `hash:net` — IPv4 subnets/CIDRs
- `hash:net6` — IPv6 subnets
- `hash:mac` — MAC addresses

```bash
firewall-cmd --new-ipset=mylist --type=hash:net --permanent
```

---

**Q45. How do I bulk-load IPs into an ipset?**

```bash
# File format: one IP or CIDR per line
cat > /tmp/blocklist.txt << 'EOF'
1.2.3.4
5.6.7.0/24
10.20.30.0/24
EOF

firewall-cmd --ipset=blocklist --add-entries-from-file=/tmp/blocklist.txt --permanent
```

---

**Q46. How do I use an ipset to block traffic?**

```bash
# Method 1: assign ipset as a zone source (simplest)
firewall-cmd --zone=drop --add-source=ipset:blocklist --permanent

# Method 2: rich rule (more flexible)
firewall-cmd --zone=public --add-rich-rule='
  rule source ipset="blocklist" drop' --permanent

firewall-cmd --reload
```

---

**Q47. Can IP sets have timeouts (automatic expiry)?**

Yes — firewalld's ipset interface supports timeouts natively in two ways:

**1. Set-level default timeout** (permanent — survives `firewalld` reload):
```bash
firewall-cmd --permanent --new-ipset=temp-block --type=hash:ip \
  --option=timeout=3600   # entries expire after 1 hour by default
firewall-cmd --reload
```

**2. Per-entry timeout** (runtime only — cannot be combined with `--permanent`):
```bash
# Entry expires after 1800 seconds regardless of the set's default
firewall-cmd --ipset=temp-block --add-entry=198.51.100.50 --timeout=1800

# Entry uses the set's default timeout
firewall-cmd --ipset=temp-block --add-entry=198.51.100.51
```

> Timed entries are **runtime only**. They are lost on `firewalld` restart or reload. If you need persistence, re-add them from a script on startup.

For use-cases that require kernel-native expiry outside of firewalld's management, you can also create a raw nftables set with `flags timeout`:
```bash
nft add set inet custom_filter temp_block \
    '{ type ipv4_addr; flags dynamic, timeout; timeout 10m; }'
```

---

## Part 8 — Logging and Troubleshooting

**Q48. How do I log all dropped/rejected packets?**

```bash
firewall-cmd --set-log-denied=all
```

Values: `off` (default), `unicast`, `broadcast`, `multicast`, `all`.

---

**Q49. Where do firewall log entries appear?**

Denied-packet log entries are kernel messages (generated by nftables' `log` statement). They appear in:
```bash
journalctl -k --grep="filter_IN"      # input chain logs
journalctl -k --grep="filter_FWD"     # forward chain logs
```

---

**Q50. How do I read a firewall log line?**

Example:
```
filter_IN_public_deny: IN=eth0 SRC=1.2.3.4 DST=10.0.0.1 PROTO=TCP SPT=54321 DPT=8080 SYN
```
- `filter_IN_public_deny` → chain name → zone `public`, packet was denied
- `IN=eth0` → arrived on eth0
- `SRC`/`DST` → source/destination IPs
- `DPT=8080` → destination port that was blocked
- `SYN` → TCP SYN (connection attempt)

---

**Q51. How do I trace a specific packet through all nftables chains?**

```bash
# Add a trace rule for matching packets
nft add rule inet firewalld filter_INPUT \
    ip saddr 1.2.3.4 tcp dport 8080 ct state new \
    meta nftrace set 1

# Monitor trace output
nft monitor trace

# Remove the trace rule when done (use --handle list to find the handle)
nft --handle list chain inet firewalld filter_INPUT
nft delete rule inet firewalld filter_INPUT handle <HANDLE>
```

---

**Q52. What is my systematic approach when traffic is blocked unexpectedly?**

The five questions:
1. Does the packet reach the host? (tcpdump)
2. Which interface and zone does it enter? (`--get-active-zones`, `--get-zone-of-interface`)
3. Which chain evaluates it? (`nft list chain inet firewalld filter_IN_ZONES`)
4. What verdict does the chain return? (`nft monitor trace`, `--list-all`)
5. For forwarded traffic: is IP forwarding enabled, and does the egress zone allow it?

---

**Q53. My permanent rules are correct but traffic is still blocked. What do I check?**

1. Did you `firewall-cmd --reload` after making permanent changes?
2. Are runtime and permanent in sync? Run `diff <(firewall-cmd --zone=Z --list-all) <(firewall-cmd --zone=Z --list-all --permanent)`
3. Is the rule in nftables? `nft list chain inet firewalld filter_IN_<zone>_allow`
4. Is there a conflicting rich rule or zone target overriding the allow?

---

**Q54. firewall-cmd shows a service is allowed but connections are refused. Why?**

Check:
1. The service definition has the correct port: `firewall-cmd --info-service=myapp`
2. The application is actually listening: `ss -tlnp | grep <port>`
3. The app is not bound to `127.0.0.1` only (firewalld can't help if the app refuses external connections)
4. SELinux is not blocking the bind: `ausearch -m avc -ts recent`

---

**Q55. How do I debug firewalld daemon decisions?**

```bash
firewall-cmd --debug=2     # raise daemon verbosity (0–3)
journalctl -u firewalld -f  # follow daemon log
```

---

**Q56. What is the difference between `--reload` and `--complete-reload`?**

| Command | Effect |
|---------|--------|
| `--reload` | Applies permanent config to runtime; keeps established connections |
| `--complete-reload` | Restarts the entire nftables ruleset; **drops established connections** |

Always use `--reload` in production. Use `--complete-reload` only when `--reload` fails to apply a change correctly.

---

**Q57. How do I check that my permanent configuration is valid before applying it?**

```bash
firewall-cmd --check-config
```

Returns `success` or a list of errors.

---

## Part 9 — Lockdown and Hardening

**Q58. What does lockdown mode actually protect against?**

It prevents unauthorized applications from modifying firewall rules through the D-Bus API. Without lockdown, any process running as root (or with `CAP_NET_ADMIN`) can call `firewall-cmd` and change rules. With lockdown, only whitelisted commands, users, or SELinux contexts can make changes via D-Bus.

**Important**: Lockdown does NOT prevent direct `nft` command execution. Use SELinux and auditd as complementary controls.

---

**Q59. How do I enable lockdown mode permanently?**

```bash
# Option A: command + permanent config
firewall-cmd --lockdown-on
sed -i 's/^Lockdown=.*/Lockdown=yes/' /etc/firewalld/firewalld.conf
firewall-cmd --reload

# Option B: edit config directly then reload
echo "Lockdown=yes" >> /etc/firewalld/firewalld.conf
firewall-cmd --reload
```

---

**Q60. I enabled lockdown and now firewall-cmd doesn't work. How do I fix it?**

Add firewall-cmd to the lockdown whitelist:
```bash
# If you can still run firewall-cmd (it might work if already in whitelist):
firewall-cmd --add-lockdown-whitelist-uid=0

# If completely locked out: edit the whitelist XML directly
cat > /etc/firewalld/lockdown-whitelist.xml << 'EOF'
<?xml version="1.0" encoding="utf-8"?>
<whitelist>
  <command name="/usr/bin/python3 -s /usr/bin/firewall-cmd*"/>
  <user id="0"/>
</whitelist>
EOF
firewall-cmd --reload
```

---

**Q61. Which zone target should I use for internet-facing zones?**

`DROP` — silently discard packets that don't match any rule. This prevents confirming to attackers that the host is reachable and avoids generating ICMP error responses that could be used for reconnaissance.

---

**Q62. Should I use interface-based or source-based zones for management traffic?**

Source-based zones for management traffic. This ensures that even if a different device is plugged into the same physical interface, it doesn't automatically get management-level access. Management traffic is identified by its source IP, not by which cable it uses.

---

**Q63. What RHEL 10 STIG requirements relate to firewalld?**

Key STIG requirements:
- firewalld must be installed and running
- Default zone must not be `trusted`
- SSH must remain accessible (don't lock out the admin)
- firewalld config files must have appropriate permissions (0640, owned by root)
- Logging must be enabled for denied packets in compliance environments

---

## Part 10 — nftables Deep Dive

**Q64. What is the `inet` address family in nftables?**

The `inet` family handles both IPv4 and IPv6 traffic in a single table. firewalld uses `inet` for its `firewalld` table, which means all its rules apply to both protocols. When writing custom tables, use `inet` for dual-stack coverage rather than writing separate `ip` and `ip6` tables.

---

**Q65. How do I find the handle number needed to delete an nftables rule?**

```bash
nft --handle list chain inet firewalld filter_INPUT
# Output includes: ... # handle 42
nft delete rule inet firewalld filter_INPUT handle 42
```

---

**Q66. What is an nftables verdict map (vmap)?**

A verdict map allows you to dispatch packets to different verdicts (accept, drop, goto chain, etc.) based on a key value, in a single O(1) lookup:

```bash
nft add map inet custom iface_dispatch '{ type ifname : verdict; }'
nft add element inet custom iface_dispatch '{ "eth0" : drop, "lo" : accept }'
nft add rule inet custom input iifname vmap @iface_dispatch
```

---

**Q67. What is an nftables meter?**

A meter is an anonymous, per-element rate-limiting data structure. Unlike named sets, meters are defined inline in a rule and track state per key (e.g., per source IP):

```bash
nft add rule inet custom input \
    tcp dport 80 ct state new \
    meter http_rate { ip saddr limit rate over 100/second } \
    drop
```

---

**Q68. What is an nftables flowtable?**

A flowtable offloads established TCP/UDP flows to a fast-path in the kernel (or hardware NIC), bypassing the full ruleset for subsequent packets in an accepted flow. This dramatically increases forwarding throughput. Flowtables bypass connection tracking for offloaded packets, so they should only be used after the firewall has accepted a connection.

---

**Q69. What nftables hook priority does firewalld use?**

firewalld registers its `filter_INPUT`, `filter_OUTPUT`, and `filter_FORWARD` chains at priority **-1**. Custom chains at priority 0 run after firewalld. To run before firewalld, use priority **-2** or lower.

---

**Q70. What is the safest way to apply a new nftables ruleset without disrupting production?**

Use `nft -f <file>` for atomic application. The entire file is validated and applied as a single transaction — either all rules apply or none. This is far safer than applying rules one at a time with `nft add rule`.

---

**Q71. How do I make custom nftables rules survive a `firewall-cmd --reload`?**

`firewall-cmd --reload` only reloads firewalld's own rules. Your custom table in `inet custom_filter` will survive a reload (firewalld doesn't touch other tables). However, you still need to persist your rules across reboots — either via a systemd unit (recommended) or by including your file in `/etc/sysconfig/nftables.conf`.

---

## Part 11 — Container and Lab Environment

**Q72. Why use rootless Podman containers as lab nodes instead of VMs?**

- Zero cost: no hypervisor license, no CPU overhead
- Fast: containers start in seconds
- Realistic: RHEL UBI 10 with real firewalld and nftables
- Isolated: each container has its own network namespace
- Reproducible: `podman rm -f node1 && podman run ...` resets in seconds
- Scriptable: `start-lab.sh` / `reset-lab.sh` automate the entire environment

---

**Q73. Why do rootless containers need `--cap-add NET_ADMIN --cap-add SYS_ADMIN`?**

firewalld and nftables require elevated capabilities to modify kernel netfilter tables. In a rootless container, these capabilities are granted within the container's user namespace — the container root has the capability scoped to its own network namespace, not the host's.

---

**Q74. Can firewalld rules in a container affect the host?**

Not with rootless Podman. Rootless containers run in their own network namespace. nftables rules inside the container only affect traffic within that namespace. The host's nftables rules are completely separate. This is safe for lab use.

---

**Q75. What networking does rootless Podman use on RHEL 10?**

RHEL 10 uses **Podman 5.x with Netavark** as the network stack. For rootless containers, Podman uses **pasta** (not slirp4netns) for network connectivity. Pasta provides better performance and supports more network features. Custom lab networks created with `podman network create` use Netavark with user-mode routing between containers.

---

## Part 12 — Advanced and Operational

**Q76 (Bonus). How do I automate firewall configuration with Ansible?**

Use the `ansible.posix.firewalld` module:
```yaml
- name: Allow HTTP
  ansible.posix.firewalld:
    service: http
    zone: public
    state: enabled
    permanent: true
    immediate: true
```

Set both `permanent: true` and `immediate: true` to apply to both runtime and permanent simultaneously (no separate reload needed).

---

**Q77 (Bonus). How do I migrate a firewalld config from RHEL 9 to RHEL 10?**

1. On RHEL 9: `tar czf firewalld-backup.tar.gz /etc/firewalld/`
2. On RHEL 10: restore the archive
3. Verify: `firewall-cmd --check-config`
4. Check for deprecated features: review zone XML for `<rule>` direct elements, as the direct interface is deprecated
5. Reload: `firewall-cmd --reload`

Most RHEL 9 configurations are compatible with RHEL 10 — the main change is the removal of the iptables direct interface.

---

*Quick Reference: [cheatsheet.md](cheatsheet.md) | Full Course: [README.md](README.md)*

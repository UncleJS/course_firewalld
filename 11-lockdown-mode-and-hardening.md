# Module 11 — Lockdown Mode and Hardening

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Learning Objectives](#learning-objectives)
3. [11.1 — The Threat: Unauthorized Firewall Modification](#111-the-threat-unauthorized-firewall-modification)
4. [11.2 — How Lockdown Mode Works](#112-how-lockdown-mode-works)
5. [11.3 — Enabling Lockdown Mode](#113-enabling-lockdown-mode)
6. [11.4 — The Lockdown Whitelist](#114-the-lockdown-whitelist)
7. [11.5 — Hardening Zones](#115-hardening-zones)
8. [11.6 — Detecting Unauthorized Modifications](#116-detecting-unauthorized-modifications)
9. [11.7 — SELinux Integration](#117-selinux-integration)
10. [11.8 — CIS and STIG Hardening Recommendations](#118-cis-and-stig-hardening-recommendations)
11. [11.9 — Hardening firewalld.conf](#119-hardening-firewalldconf)
12. [Lab 11 — Lockdown Mode and Hardening](#lab-11-lockdown-mode-and-hardening)
13. [Key Takeaways](#key-takeaways)

---

↑ [Back to TOC](#table-of-contents)

## Prerequisites
- Modules 01–10 completed
- Familiarity with D-Bus, PolicyKit, and systemd services
- Lab environment running (`~/firewalld-lab/start-lab.sh`)

---

↑ [Back to TOC](#table-of-contents)

## Learning Objectives
By the end of this module you will be able to:
1. Explain what firewalld lockdown mode is and what it protects against
2. Configure the lockdown whitelist to allow only specific applications to modify firewall rules
3. Harden firewall zones using defense-in-depth techniques
4. Implement a minimal-surface configuration following the principle of least privilege
5. Detect and respond to unauthorized firewall modifications
6. Apply RHEL 10 security baselines (STIG/CIS) relevant to firewalld
7. Integrate firewalld hardening with SELinux and auditd

---

↑ [Back to TOC](#table-of-contents)

## 11.1 — The Threat: Unauthorized Firewall Modification

On a multi-tenant or shared system, any process running as root (or with `CAP_NET_ADMIN`) can modify firewall rules. Without lockdown mode, a compromised web server running as root could:

```bash
# Without lockdown: any root process can do this
firewall-cmd --zone=public --add-port=4444/tcp    # open a backdoor
firewall-cmd --zone=public --add-masquerade       # enable traffic pivoting
```

firewalld's **lockdown mode** addresses this by requiring applications to be explicitly whitelisted before they can make changes through the D-Bus API.

---

↑ [Back to TOC](#table-of-contents)

## 11.2 — How Lockdown Mode Works

```
Application (e.g., NetworkManager)
         │
         │  D-Bus call: org.fedoraproject.FirewallD1.addService(...)
         ▼
    firewalld daemon
         │
         ├── Is lockdown enabled?  ──No──► Process request
         │
         └── Yes: Check lockdown whitelist
                   │
                   ├── Application found? ──Yes──► Process request
                   │
                   └── No ──► Reject with AccessDenied
```

Lockdown applies to **D-Bus modifications only**. The `firewall-cmd` CLI tool communicates through D-Bus — so it is also subject to lockdown.

Direct `nft` commands bypass firewalld entirely and are **not** subject to lockdown mode.  
This is why SELinux + auditd are needed as complementary controls.

---

↑ [Back to TOC](#table-of-contents)

## 11.3 — Enabling Lockdown Mode

```bash
# Enable at runtime
firewall-cmd --lockdown-on

# Verify
firewall-cmd --query-lockdown    # → yes

# Disable (for testing)
firewall-cmd --lockdown-off

# Make permanent
firewall-cmd --lockdown-on
# Then edit /etc/firewalld/firewalld.conf and set:
#   Lockdown=yes
# Then reload:
firewall-cmd --reload
```

Alternatively, edit `/etc/firewalld/firewalld.conf` directly:
```ini
# /etc/firewalld/firewalld.conf
Lockdown=yes
```

---

↑ [Back to TOC](#table-of-contents)

## 11.4 — The Lockdown Whitelist

The whitelist lives at `/etc/firewalld/lockdown-whitelist.xml`.

### 11.4.1 Whitelist structure

```xml
<?xml version="1.0" encoding="utf-8"?>
<whitelist>
  <!-- Allow firewall-cmd run by root from any terminal -->
  <command name="/usr/bin/python3 -s /usr/bin/firewall-cmd*"/>

  <!-- Allow NetworkManager to manage firewall zones -->
  <selinux context="system_u:system_r:NetworkManager_t:s0"/>

  <!-- Allow a specific user ID -->
  <user id="0"/>

  <!-- Allow by username -->
  <user name="netadmin"/>
</whitelist>
```

Entry types:

| Type | Syntax | Notes |
|------|--------|-------|
| Command | `<command name="..."/>` | Glob `*` supported at end; matches `/proc/PID/cmdline` |
| SELinux context | `<selinux context="..."/>` | Matches the calling process's SELinux label |
| User ID | `<user id="0"/>` | UID number |
| User name | `<user name="alice"/>` | Username string |

### 11.4.2 Managing the whitelist via firewall-cmd

```bash
# List current whitelist
firewall-cmd --list-lockdown-whitelist-commands
firewall-cmd --list-lockdown-whitelist-contexts
firewall-cmd --list-lockdown-whitelist-uids
firewall-cmd --list-lockdown-whitelist-users

# Add entries
firewall-cmd --add-lockdown-whitelist-command='/usr/bin/python3 -s /usr/bin/firewall-cmd*'
firewall-cmd --add-lockdown-whitelist-uid=0
firewall-cmd --add-lockdown-whitelist-user=netadmin
firewall-cmd --add-lockdown-whitelist-context='system_u:system_r:NetworkManager_t:s0'

# Remove entries
firewall-cmd --remove-lockdown-whitelist-uid=1001

# Save permanently
firewall-cmd --runtime-to-permanent
# or use --permanent flag from the start with each --add-lockdown-* command
```

### 11.4.3 What happens when a non-whitelisted process tries to modify firewalld

```bash
# With lockdown on and the calling process not whitelisted:
firewall-cmd --zone=public --add-port=9999/tcp
# Error: COMMAND_FAILED: 'python3 -s /usr/bin/firewall-cmd ...' failed:
#   ACCESS_DENIED: lockdown is enabled. Please use 'firewall-cmd --reload'
#   ... to revert any recent changes.
```

The error is also logged to the firewalld journal:
```bash
journalctl -u firewalld | grep "ACCESS_DENIED"
```

---

↑ [Back to TOC](#table-of-contents)

## 11.5 — Hardening Zones

Lockdown mode prevents unauthorized *changes* to the firewall. Zone hardening reduces the attack surface of the rules themselves.

### 11.5.1 Principle of least privilege for zones

| Principle | Implementation |
|-----------|---------------|
| No service should be open unless required | Audit with `--list-all` and remove unused services |
| Use specific source IPs, not open zones | `--add-source=` instead of `--add-interface=` |
| Drop rather than reject when possible | `--set-target=DROP` for external-facing zones |
| Separate traffic by zone function | Never put management and production traffic in the same zone |

### 11.5.2 Audit open services

```bash
# Show everything open across all zones
for zone in $(firewall-cmd --get-zones); do
    echo "=== $zone ==="
    firewall-cmd --zone=$zone --list-all
done
```

### 11.5.3 Remove default services you don't need

By default, the `public` zone allows `ssh` and `dhcpv6-client`. Remove what you don't need:

```bash
# If this system doesn't need DHCPv6 client
firewall-cmd --zone=public --remove-service=dhcpv6-client --permanent

# If SSH is managed separately (e.g., only via internal zone)
firewall-cmd --zone=public --remove-service=ssh --permanent
firewall-cmd --zone=internal --add-service=ssh --permanent
firewall-cmd --reload
```

### 11.5.4 Set zone targets

Zone **targets** determine what happens to packets that don't match any rule:

| Target | Behavior | Use case |
|--------|----------|----------|
| `default` | REJECT with ICMP admin-prohibited | Most zones |
| `ACCEPT` | Accept all unmatched packets | Trusted/internal zones only |
| `DROP` | Silently drop unmatched packets | External/hostile zones |
| `REJECT` | Explicit REJECT (same as default) | When you want explicit behavior |

```bash
# Set external-facing zone to DROP
firewall-cmd --zone=external --set-target=DROP --permanent

# Set truly trusted internal zone to ACCEPT
firewall-cmd --zone=trusted --set-target=ACCEPT --permanent

firewall-cmd --reload
```

> **DROP vs REJECT**: `DROP` is stealthier (attackers don't get confirmation the host exists), but makes debugging harder. `REJECT` is more RFC-compliant and friendlier to legitimate clients that mis-dial. Choose based on context.

### 11.5.5 Restrict ICMP

```bash
# Block ping from external zone
firewall-cmd --zone=external --add-icmp-block=echo-request --permanent

# Allow traceroute only from management zone
firewall-cmd --zone=external --add-icmp-block=echo-reply --permanent
firewall-cmd --zone=mgmt --add-icmp-block-inversion --permanent   # allow all ICMP in mgmt

firewall-cmd --reload
```

```bash
# List blocked ICMP types
firewall-cmd --zone=external --list-icmp-blocks
```

### 11.5.6 Use source-based zones instead of interface-based

Interface-based zone assignment is coarse. Source-based is more precise:

```bash
# Only allow management traffic from the dedicated management subnet
firewall-cmd --zone=mgmt --add-source=192.168.100.0/24 --permanent

# Assign interface to a catch-all restrictive zone
firewall-cmd --zone=external --add-interface=eth0 --permanent

firewall-cmd --reload
```

Now management traffic from 192.168.100.0/24 gets the `mgmt` zone rules (permissive), and everything else on eth0 gets the `external` rules (restrictive).

---

↑ [Back to TOC](#table-of-contents)

## 11.6 — Detecting Unauthorized Modifications

### 11.6.1 Audit the firewalld config directory

```bash
# Watch for changes with auditd
auditctl -w /etc/firewalld/ -p wa -k firewall-config-change
auditctl -w /usr/lib/firewalld/ -p wa -k firewall-shipped-change

# Search for recent changes
ausearch -k firewall-config-change --interpret --since recent
```

### 11.6.2 Watch D-Bus calls in real time

```bash
# Monitor all D-Bus messages to firewalld
dbus-monitor --system "destination=org.fedoraproject.FirewallD1" 2>/dev/null
```

### 11.6.3 Diff against a known-good baseline

```bash
# Save baseline
cp -r /etc/firewalld /etc/firewalld.baseline.$(date +%Y%m%d)

# Later, check for drift
diff -r /etc/firewalld.baseline.20260224 /etc/firewalld
```

### 11.6.4 Use AIDE or similar FIM tools

```bash
# Add firewalld config to AIDE database
# In /etc/aide.conf:
/etc/firewalld CONTENT_EX
/usr/lib/firewalld CONTENT_EX

aide --check
```

---

↑ [Back to TOC](#table-of-contents)

## 11.7 — SELinux Integration

SELinux provides mandatory access control that operates independently of firewalld. Together they form a defense-in-depth posture.

### 11.7.1 firewalld's SELinux context

```bash
# firewalld runs in its own SELinux domain
ps -eZ | grep firewalld
# system_u:system_r:firewalld_t:s0  ...  /usr/sbin/firewalld

# The firewalld domain is allowed to:
# - manage nftables rules
# - write to /etc/firewalld/
# - communicate on D-Bus
sesearch --allow --source firewalld_t | head -20
```

### 11.7.2 Prevent nft from being called outside firewalld

Without additional policy, any `unconfined_t` process (i.e., a root shell) can call `nft` directly and bypass firewalld entirely. Lockdown mode does NOT prevent this.

Defense: use SELinux to constrain `nft` execution.

```bash
# Check current nft file context
ls -Z /usr/sbin/nft
# system_u:object_r:nft_exec_t:s0

# In a hardened environment, restrict which domains can exec nft_exec_t
# This requires custom policy — beyond scope, but worth knowing
```

### 11.7.3 SELinux booleans related to networking

```bash
# List network-related booleans
getsebool -a | grep -E "(ftp|http|ssh|nis|nfs|nmap|firewall)"

# Example: allow httpd to make network connections
setsebool -P httpd_can_network_connect on
```

---

↑ [Back to TOC](#table-of-contents)

## 11.8 — CIS and STIG Hardening Recommendations

### Relevant CIS Benchmark items (RHEL 10)

| CIS ID | Recommendation | firewall-cmd implementation |
|--------|---------------|---------------------------|
| 3.5.1.1 | Ensure firewalld is installed and enabled | `systemctl enable --now firewalld` |
| 3.5.1.2 | Ensure iptables not in use alongside firewalld | `dnf remove iptables-legacy` |
| 3.5.1.3 | Ensure nftables not running separately | Verify `nft` rules come only from firewalld |
| 3.5.1.4 | Ensure default zone is set | `firewall-cmd --get-default-zone` → not `trusted` |
| 3.5.1.5 | Ensure no unneeded services open | Audit with `--list-all` per zone |
| 3.5.1.6 | Ensure only approved ports are open | Document and enforce per service |

### Relevant STIG items (RHEL 10 STIG v1)

```bash
# RHEL-10-040030: firewalld must be running
systemctl is-active firewalld

# RHEL-10-040080: default zone must not be trusted
firewall-cmd --get-default-zone    # should NOT return "trusted"

# RHEL-10-040090: SSH must be allowed (so remediation doesn't lock out admin)
firewall-cmd --zone=public --query-service=ssh

# RHEL-10-040100: firewalld config files must have correct permissions
stat /etc/firewalld/firewalld.conf
# Expect: 0600 or 0640, owned by root
```

### Applying correct file permissions

```bash
chmod 0640 /etc/firewalld/firewalld.conf
chmod 0640 /etc/firewalld/zones/*.xml
chown -R root:root /etc/firewalld/
```

---

↑ [Back to TOC](#table-of-contents)

## 11.9 — Hardening firewalld.conf

Key settings in `/etc/firewalld/firewalld.conf`:

```ini
# /etc/firewalld/firewalld.conf — hardened example

# Activate lockdown
Lockdown=yes

# Log all denied packets during initial deployment; switch to 'off' in production
LogDenied=unicast

# Don't load IPv6 support if not used (reduces attack surface)
# IPv6_rpfilter=yes     # keep enabled — prevents IP spoofing

# Flush all nftables rules when firewalld stops (prevents policy gap)
CleanupModulesOnExit=yes

# Don't allow individual daemons to bypass firewall via automatic hole-punching
IndividualCalls=no

# RHEL 10 only: prevent container-published ports from bypassing zone rules
StrictForwardPorts=yes
```

---

↑ [Back to TOC](#table-of-contents)

## Lab 11 — Lockdown Mode and Hardening

**Objective**: Enable lockdown, configure the whitelist, harden zones, and verify the configuration.

### Setup

```bash
~/firewalld-lab/start-lab.sh
podman exec -it node1 bash
```

---

### Step 1 — Enable lockdown mode

```bash
# Enable lockdown
firewall-cmd --lockdown-on
firewall-cmd --query-lockdown    # → yes
```

---

### Step 2 — Test that lockdown blocks changes

```bash
# As root, try to add a port (firewall-cmd calls D-Bus)
# This should fail because the command isn't whitelisted yet
firewall-cmd --zone=public --add-port=9999/tcp
# Expect: ACCESS_DENIED error
```

---

### Step 3 — Add firewall-cmd to the whitelist

```bash
# Add the firewall-cmd Python invocation to the whitelist
firewall-cmd --add-lockdown-whitelist-command='/usr/bin/python3 -s /usr/bin/firewall-cmd*'

# Also allow root UID
firewall-cmd --add-lockdown-whitelist-uid=0

# Verify
firewall-cmd --list-lockdown-whitelist-commands
firewall-cmd --list-lockdown-whitelist-uids
```

---

### Step 4 — Retry the port addition

```bash
firewall-cmd --zone=public --add-port=9999/tcp
# Should now succeed

# Clean it up
firewall-cmd --zone=public --remove-port=9999/tcp
```

---

### Step 5 — Harden the external zone

```bash
# Set target to DROP
firewall-cmd --zone=external --set-target=DROP

# Block ping
firewall-cmd --zone=external --add-icmp-block=echo-request

# Remove unnecessary services
firewall-cmd --zone=external --list-services
# Remove dhcpv6-client if present
firewall-cmd --zone=external --remove-service=dhcpv6-client 2>/dev/null || true

# Verify
firewall-cmd --zone=external --list-all
```

---

### Step 6 — Verify the nftables rules for DROP target

```bash
nft list chain inet firewalld filter_IN_external
# Look for: policy drop  or  drop at the end of the chain
```

---

### Step 7 — Audit all open services

```bash
for zone in $(firewall-cmd --get-zones); do
    services=$(firewall-cmd --zone=$zone --list-services)
    ports=$(firewall-cmd --zone=$zone --list-ports)
    if [ -n "$services" ] || [ -n "$ports" ]; then
        echo "=== $zone: services=[$services] ports=[$ports] ==="
    fi
done
```

---

### Step 8 — Set up auditd monitoring

```bash
# Install audit if not present
dnf install -y audit 2>/dev/null || true

# Add audit watch on firewalld config
auditctl -w /etc/firewalld/ -p wa -k firewall-config-change

# Trigger a change and verify it's logged
firewall-cmd --set-log-denied=all --permanent
ausearch -k firewall-config-change --interpret 2>/dev/null || \
    journalctl -k --grep="firewall" --since="1 minute ago"
```

---

### Step 9 — Save the hardened whitelist permanently

```bash
# Write permanent whitelist
cat > /etc/firewalld/lockdown-whitelist.xml << 'EOF'
<?xml version="1.0" encoding="utf-8"?>
<whitelist>
  <command name="/usr/bin/python3 -s /usr/bin/firewall-cmd*"/>
  <user id="0"/>
</whitelist>
EOF

# Enable lockdown permanently in config
sed -i 's/^Lockdown=.*/Lockdown=yes/' /etc/firewalld/firewalld.conf
# or add if not present:
grep -q "^Lockdown=" /etc/firewalld/firewalld.conf || \
    echo "Lockdown=yes" >> /etc/firewalld/firewalld.conf

firewall-cmd --reload
firewall-cmd --query-lockdown    # → yes
```

---

### Step 10 — Cleanup

```bash
# Restore for subsequent modules
firewall-cmd --lockdown-off
firewall-cmd --zone=external --set-target=default
firewall-cmd --zone=external --remove-icmp-block=echo-request
```

---

### Lab Verification Checklist

- [ ] `firewall-cmd --query-lockdown` returns `yes` after enabling
- [ ] Unauthenticated D-Bus call returns `ACCESS_DENIED`
- [ ] After adding firewall-cmd to whitelist, port additions work again
- [ ] `filter_IN_external` chain in nftables reflects DROP target
- [ ] ICMP block for `echo-request` is present in external zone
- [ ] Audit rule watches `/etc/firewalld/`
- [ ] `/etc/firewalld/lockdown-whitelist.xml` persists after reload

---

↑ [Back to TOC](#table-of-contents)

## Key Takeaways

| Topic | Key Point |
|-------|-----------|
| Lockdown mode | Controls who can modify firewall via D-Bus; doesn't stop direct `nft` calls |
| Whitelist | Match by command, SELinux context, UID, or username |
| Zone targets | `DROP` for hostile-facing zones; `ACCEPT` only for fully trusted |
| Source-based zones | More precise than interface-based; supports overlapping subnets |
| Defense in depth | Lockdown + SELinux + auditd together; no single control is sufficient |
| CIS/STIG | Default zone must not be `trusted`; firewalld must be enabled; SSH must remain accessible |

---

*Next: [Module 12 — Direct Rules and Advanced nftables](12-direct-rules-and-advanced-nftables.md)*

---

© 2026 Jaco Steyn — Licensed under CC BY-SA 4.0

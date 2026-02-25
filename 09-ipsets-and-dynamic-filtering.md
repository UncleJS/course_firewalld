# Module 09 — IP Sets and Dynamic Filtering

> **Goal:** Use IP sets to match large collections of addresses efficiently,
> build dynamic block lists with automatic expiry, implement geo-blocking
> pipelines, and understand how sets relate to the nftables set primitives
> covered in Module 02.

---

## Table of Contents

1. [1. Why IP Sets?](#1-why-ip-sets)
2. [2. IP Set Types](#2-ip-set-types)
3. [3. Creating and Managing IP Sets](#3-creating-and-managing-ip-sets)
4. [4. Adding and Removing Entries](#4-adding-and-removing-entries)
5. [5. Timeout-Based Entries (Dynamic Expiry)](#5-timeout-based-entries-dynamic-expiry)
6. [6. Using Sets in Rich Rules](#6-using-sets-in-rich-rules)
7. [7. Using Sets in Zones](#7-using-sets-in-zones)
8. [8. Populating Sets from Files](#8-populating-sets-from-files)
9. [9. Geo-blocking with IP Sets](#9-geo-blocking-with-ip-sets)
10. [10. IP Sets in nftables](#10-ip-sets-in-nftables)
11. [11. IP Set XML Format](#11-ip-set-xml-format)
12. [Lab 9 — Dynamic Block List with Auto-Expiry](#lab-9-dynamic-block-list-with-auto-expiry)

---

↑ [Back to TOC](#table-of-contents)

## 1. Why IP Sets?

Consider blocking 10,000 known-malicious IP addresses. The naive approach:
10,000 individual rich rules:

```bash
firewall-cmd --zone=public --add-rich-rule='rule family="ipv4" source address="1.2.3.4" drop'
firewall-cmd --zone=public --add-rich-rule='rule family="ipv4" source address="1.2.3.5" drop'
# ... 9,998 more times
```

Problems:
1. **Performance:** Each packet is checked against 10,000 rules sequentially
2. **Memory:** 10,000 nftables rules consume significant kernel memory
3. **Management:** Adding/removing individual entries is painful
4. **Reload time:** Each reload with 10,000 rules takes longer

IP sets solve all of these:

```bash
# Create a set once
firewall-cmd --permanent --new-ipset=malicious --type=hash:ip

# Add 10,000 entries (instantly — sets use hash tables)
# ... (script adds entries)

# ONE rule references the entire set
firewall-cmd --permanent --zone=public --add-rich-rule='
  rule family="ipv4" source ipset="malicious" drop
'
```

The kernel uses hash lookup — checking a packet against a 10,000-entry hash set
is O(1), not O(10,000). Sets also support efficient updates: adding or removing
an entry doesn't require reloading the entire ruleset.

---

↑ [Back to TOC](#table-of-contents)

## 2. IP Set Types

firewalld supports several IP set types, corresponding to nftables set types:

| Type | Contents | Flag | Use case |
|------|----------|------|---------|
| `hash:ip` | Individual IPv4/IPv6 addresses | - | Block/allow specific hosts |
| `hash:net` | CIDR networks | `interval` | Block/allow subnets |
| `hash:mac` | MAC addresses | - | Layer 2 filtering |
| `hash:ip,port` | IP + port combination | - | Per-service blocking |
| `hash:net,port` | Network + port combination | `interval` | Complex filtering |

The most commonly used types are `hash:ip` and `hash:net`.

---

↑ [Back to TOC](#table-of-contents)

## 3. Creating and Managing IP Sets

### Creating a set

```bash
# Basic hash:ip set
firewall-cmd --permanent --new-ipset=blocklist --type=hash:ip

# hash:net set (for CIDR ranges — requires interval flag)
firewall-cmd --permanent --new-ipset=blocked-nets \
  --type=hash:net \
  --option=family=inet

# IPv6 set
firewall-cmd --permanent --new-ipset=ipv6-blocklist \
  --type=hash:ip \
  --option=family=inet6

# Set with timeout support (for auto-expiring entries)
firewall-cmd --permanent --new-ipset=temp-blocklist \
  --type=hash:ip \
  --option=timeout=3600  # Default timeout: 3600 seconds (1 hour)
```

### Listing sets

```bash
# List all set names
firewall-cmd --get-ipsets

# Get details of a specific set
firewall-cmd --info-ipset=blocklist

# List entries in a set
firewall-cmd --ipset=blocklist --get-entries
```

### Deleting a set

```bash
# Remove a set (it must not be referenced by any zone or rule first)
firewall-cmd --permanent --delete-ipset=blocklist
```

---

↑ [Back to TOC](#table-of-contents)

## 4. Adding and Removing Entries

### Single entries

```bash
# Add a single IP
firewall-cmd --permanent --ipset=blocklist --add-entry=192.168.1.100

# Add a CIDR range (to a hash:net set)
firewall-cmd --permanent --ipset=blocked-nets --add-entry=198.51.100.0/24

# Add a MAC address (to a hash:mac set)
firewall-cmd --permanent --ipset=mac-allowlist --add-entry=aa:bb:cc:dd:ee:ff

# Remove an entry
firewall-cmd --permanent --ipset=blocklist --remove-entry=192.168.1.100

# Check if an entry exists
firewall-cmd --ipset=blocklist --query-entry=192.168.1.100
# Returns: yes or no
```

### Bulk entry management

For large sets, direct XML editing or file-based loading is more efficient:

```bash
# List all current entries to a file
firewall-cmd --ipset=blocklist --get-entries > /tmp/blocklist-entries.txt

# The entries file format is one entry per line
# Edit as needed, then reload via XML (see section 8)
```

> **📝 NOTE — Runtime vs Permanent for sets**
> Like zones and services, IP set changes have runtime and permanent forms.
> Without `--permanent`, entries are added to the runtime state only and are
> lost on reload. With `--permanent`, they're written to the XML file.
>
> Exception: entries added with `--timeout` (section 5) are always runtime only.

---

↑ [Back to TOC](#table-of-contents)

## 5. Timeout-Based Entries (Dynamic Expiry)

Timeout entries are the key feature for dynamic filtering — blocking an
attacker temporarily without leaving a permanent rule.

### Creating a set with default timeout

```bash
# Set where all entries expire after 1 hour by default
firewall-cmd --permanent --new-ipset=temp-block \
  --type=hash:ip \
  --option=timeout=3600

firewall-cmd --reload
```

### Adding entries with timeout

```bash
# Add an entry that expires in 30 minutes (overrides default)
# Note: timeout entries are RUNTIME ONLY (no --permanent)
firewall-cmd --ipset=temp-block --add-entry=198.51.100.50 --timeout=1800

# Add with the set's default timeout
firewall-cmd --ipset=temp-block --add-entry=198.51.100.51
```

> **⚠️  IMPORTANT — Timeout entries are runtime only**
> You cannot use `--permanent` with `--timeout`. Timed entries only exist in
> the runtime state and expire automatically. This is by design — they're meant
> to be temporary.

### Automatic IP blocking script

This pattern is common for automated incident response:

```bash
#!/usr/bin/env bash
# /usr/local/bin/block-ip.sh
# Usage: block-ip.sh <IP> [timeout_seconds]

IP="$1"
TIMEOUT="${2:-3600}"  # Default 1 hour

# Validate IP format
if ! [[ "$IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Invalid IP: $IP"
  exit 1
fi

# Add to temporary block set
firewall-cmd --ipset=temp-block --add-entry="$IP" --timeout="$TIMEOUT"
echo "Blocked $IP for ${TIMEOUT}s"
logger -t firewalld-block "Blocked $IP for ${TIMEOUT}s"
```

Integrate with fail2ban, intrusion detection systems, or log parsers:

```bash
# fail2ban action (simplified)
actionban = /usr/local/bin/block-ip.sh <ip> 3600
actionunban = firewall-cmd --ipset=temp-block --remove-entry=<ip>
```

---

↑ [Back to TOC](#table-of-contents)

## 6. Using Sets in Rich Rules

Rich rules reference sets with `source ipset="setname"`:

```bash
# Drop all traffic from IPs in the blocklist
firewall-cmd --permanent --zone=public --add-rich-rule='
  rule family="ipv4" source ipset="blocklist" drop
'

# Log then drop
firewall-cmd --permanent --zone=public --add-rich-rule='
  rule family="ipv4" source ipset="blocklist"
  log prefix="BLOCKLIST-HIT: " level="warning" limit value="5/m"
  drop
'

# Allow access for IPs in an allowlist (higher priority)
firewall-cmd --permanent --zone=public --add-rich-rule='
  rule priority="-100" family="ipv4" source ipset="allowlist"
  service name="ssh"
  accept
'

# Then reject everyone else trying SSH
firewall-cmd --permanent --zone=public --add-rich-rule='
  rule priority="0" family="ipv4"
  service name="ssh"
  reject type="tcp-reset"
'
```

---

↑ [Back to TOC](#table-of-contents)

## 7. Using Sets in Zones

You can bind an IP set to a zone directly (as a source), so all traffic from
IPs in the set is processed by that zone's rules:

```bash
# Create a zone for VIP customers
firewall-cmd --permanent --new-zone=vip-customers

# Add services VIPs can access
firewall-cmd --permanent --zone=vip-customers --add-service=http
firewall-cmd --permanent --zone=vip-customers --add-service=https
firewall-cmd --permanent --zone=vip-customers --add-port=9000/tcp  # Premium API

# Create the VIP set
firewall-cmd --permanent --new-ipset=vip-ips --type=hash:ip

# Bind the set to the zone
firewall-cmd --permanent --zone=vip-customers --add-source=ipset:vip-ips

firewall-cmd --reload

# Add VIP IPs
firewall-cmd --permanent --ipset=vip-ips --add-entry=203.0.113.1
firewall-cmd --permanent --ipset=vip-ips --add-entry=203.0.113.2
firewall-cmd --reload
```

Note the `ipset:` prefix when using a set as a zone source.

---

↑ [Back to TOC](#table-of-contents)

## 8. Populating Sets from Files

For large sets, populate via the XML configuration file directly:

### IP set XML file format

```xml
<?xml version="1.0" encoding="utf-8"?>
<ipset type="hash:ip">
  <short>Malicious IPs</short>
  <description>Known malicious IP addresses from threat intelligence feeds.</description>
  <option name="family" value="inet"/>
  <option name="timeout" value="86400"/>
  <entry>192.168.1.100</entry>
  <entry>198.51.100.0/24</entry>
  <entry>203.0.113.5</entry>
</ipset>
```

Save to `/etc/firewalld/ipsets/malicious.xml` then reload.

### Script to build XML from a flat list

```bash
#!/usr/bin/env bash
# build-ipset-xml.sh <name> <description> <ip-file>
NAME="$1"
DESC="$2"
IPFILE="$3"

cat > "/etc/firewalld/ipsets/${NAME}.xml" << XMLEOF
<?xml version="1.0" encoding="utf-8"?>
<ipset type="hash:ip">
  <short>${NAME}</short>
  <description>${DESC}</description>
  <option name="family" value="inet"/>
XMLEOF

while IFS= read -r ip; do
  # Skip comments and empty lines
  [[ "$ip" =~ ^#|^$ ]] && continue
  echo "  <entry>${ip}</entry>" >> "/etc/firewalld/ipsets/${NAME}.xml"
done < "$IPFILE"

echo "</ipset>" >> "/etc/firewalld/ipsets/${NAME}.xml"

firewall-cmd --reload
echo "Loaded $(wc -l < "$IPFILE") entries into ${NAME}"
```

---

↑ [Back to TOC](#table-of-contents)

## 9. Geo-blocking with IP Sets

Geo-blocking restricts traffic based on country/region of origin. It requires
an IP-to-country database.

### Using ipdeny.com CIDR lists (ipdeny approach)

```bash
# Install required tools (on RHEL 10)
dnf install -y curl

# Script to download per-country CIDR list from ipdeny.com and build an ipset
cat > /usr/local/bin/build-geo-block.sh << 'SCRIPT'
#!/usr/bin/env bash
# Usage: build-geo-block.sh <COUNTRY_CODE>
COUNTRY="$1"
SETNAME="geo-block-${COUNTRY,,}"
TMPFILE=$(mktemp)

# Download CIDR list for country (using ipdeny.com)
curl -s "https://www.ipdeny.com/ipblocks/data/aggregated/${COUNTRY,,}-aggregated.zone" \
  > "$TMPFILE"

# Count entries BEFORE removing the temp file
ENTRY_COUNT=$(wc -l < "$TMPFILE")

# Create ipset XML
cat > "/etc/firewalld/ipsets/${SETNAME}.xml" << EOF
<?xml version="1.0" encoding="utf-8"?>
<ipset type="hash:net">
  <short>Geo-block: ${COUNTRY}</short>
  <description>All IP ranges allocated to ${COUNTRY}.</description>
  <option name="family" value="inet"/>
EOF

while IFS= read -r cidr; do
  [[ -z "$cidr" ]] && continue
  echo "  <entry>${cidr}</entry>" >> "/etc/firewalld/ipsets/${SETNAME}.xml"
done < "$TMPFILE"

echo "</ipset>" >> "/etc/firewalld/ipsets/${SETNAME}.xml"
rm "$TMPFILE"

firewall-cmd --reload
echo "Geo-block set '${SETNAME}' created with ${ENTRY_COUNT} networks."
SCRIPT
chmod +x /usr/local/bin/build-geo-block.sh

# Create a geo-block for a country
/usr/local/bin/build-geo-block.sh CN

# Block that country
firewall-cmd --permanent --zone=public --add-rich-rule='
  rule family="ipv4" source ipset="geo-block-cn" drop
'
firewall-cmd --reload
```

### Allowing only a specific country

The mirror image of geo-blocking: instead of dropping traffic *from* a country,
you **accept** traffic *from* one country and drop everything else. This is
useful for services that have a strictly regional user base (e.g. an internal
portal that should only be reachable from within Japan).

```bash
# Script to download per-country CIDR list from ipdeny.com and build an allow-set
cat > /usr/local/bin/build-geo-allow.sh << 'SCRIPT'
#!/usr/bin/env bash
# Usage: build-geo-allow.sh <COUNTRY_CODE>
COUNTRY="$1"
SETNAME="geo-allow-${COUNTRY,,}"
TMPFILE=$(mktemp)

# Download CIDR list for country (using ipdeny.com)
curl -s "https://www.ipdeny.com/ipblocks/data/aggregated/${COUNTRY,,}-aggregated.zone" \
  > "$TMPFILE"

# Count entries BEFORE removing the temp file
ENTRY_COUNT=$(wc -l < "$TMPFILE")

# Create ipset XML
cat > "/etc/firewalld/ipsets/${SETNAME}.xml" << EOF
<?xml version="1.0" encoding="utf-8"?>
<ipset type="hash:net">
  <short>Geo-allow: ${COUNTRY}</short>
  <description>All IP ranges allocated to ${COUNTRY} (allowlist).</description>
  <option name="family" value="inet"/>
EOF

while IFS= read -r cidr; do
  [[ -z "$cidr" ]] && continue
  echo "  <entry>${cidr}</entry>" >> "/etc/firewalld/ipsets/${SETNAME}.xml"
done < "$TMPFILE"

echo "</ipset>" >> "/etc/firewalld/ipsets/${SETNAME}.xml"
rm "$TMPFILE"

firewall-cmd --reload
echo "Geo-allow set '${SETNAME}' created with ${ENTRY_COUNT} networks."
SCRIPT
chmod +x /usr/local/bin/build-geo-allow.sh

# Build the allowlist for Japan
/usr/local/bin/build-geo-allow.sh JP

# Accept traffic from that country
firewall-cmd --permanent --zone=public --add-rich-rule='
  rule family="ipv4" source ipset="geo-allow-jp" accept
'
firewall-cmd --reload
```

#### Combined pattern: allow one country, drop everything else

Use rich rule **priorities** to ensure the accept fires before a blanket drop.
Lower priority numbers are evaluated first.

```bash
# Priority -100: accept traffic whose source is in the Japan allowlist
firewall-cmd --permanent --zone=public --add-rich-rule='
  rule priority="-100" family="ipv4" source ipset="geo-allow-jp" accept
'

# Priority 0: drop all other IPv4 traffic
firewall-cmd --permanent --zone=public --add-rich-rule='
  rule priority="0" family="ipv4" drop
'

firewall-cmd --reload
```

Packet evaluation order:
1. Packet arrives → priority `-100` rule checked first
2. Source IP is in `geo-allow-jp` → **accepted**, evaluation stops
3. Source IP is NOT in `geo-allow-jp` → falls through to priority `0` → **dropped**

> **⚠️ WARNING — Drop-all locks you out too**
> The priority `0` drop rule catches *all* IPv4 traffic not already accepted,
> including your own management connection. Always add an explicit accept for
> your own IP or subnet *before* adding the drop-all rule:
> ```bash
> # Accept your management IP first (priority -200 — runs before everything)
> firewall-cmd --permanent --zone=public --add-rich-rule='
>   rule priority="-200" family="ipv4" source address="YOUR_MGMT_IP/32" accept
> '
> firewall-cmd --reload
> # Then add the geo-allow + drop-all rules above
> ```

#### Removing geo-allow rules and sets

```bash
# Remove the drop-all rule
firewall-cmd --permanent --zone=public --remove-rich-rule='
  rule priority="0" family="ipv4" drop
'

# Remove the geo-allow rule
firewall-cmd --permanent --zone=public --remove-rich-rule='
  rule priority="-100" family="ipv4" source ipset="geo-allow-jp" accept
'

# Delete the ipset XML and reload
rm /etc/firewalld/ipsets/geo-allow-jp.xml
firewall-cmd --reload
```

---

> **📝 NOTE — Geo-blocking limitations**
> Geo-blocking is a coarse measure. Determined actors use VPNs, proxies, and
> cloud provider IPs from other regions. It's effective for blocking opportunistic
> attacks from specific regions but not for determined adversaries. Use it as
> one layer in a defence-in-depth strategy.
>
> **Geo-allowlisting carries its own risk**: any legitimate user outside the
> permitted country is silently blocked, including remote workers, travellers,
> and third-party integrations. Only use geo-allowlisting for services whose
> entire user base is known to be geographically constrained, and ensure you
> have an out-of-band management path that bypasses the restriction.

---

↑ [Back to TOC](#table-of-contents)

## 10. IP Sets in nftables

firewalld's IP sets map directly to nftables named sets. Understanding this
mapping is useful for debugging.

```bash
# After creating a firewalld ipset, find it in nftables
nft list sets | grep -A3 "blocklist"

# Or view the specific set
nft list set inet firewalld blocklist
```

Expected output:
```
table inet firewalld {
  set blocklist {
    type ipv4_addr
    elements = { 192.168.1.100, 198.51.100.50 }
  }
}
```

### nftables set operations (for debugging/testing)

```bash
# Add an entry directly to nftables (for testing — NOT permanent)
nft add element inet firewalld blocklist { 10.0.0.1 }

# Remove
nft delete element inet firewalld blocklist { 10.0.0.1 }

# List with counters (if set has counter flag)
nft list set inet firewalld blocklist
```

> **⚠️  IMPORTANT — Direct nftables set modifications are runtime only**
> Adding entries to nftables sets directly is NOT reflected in firewalld's
> permanent config and is wiped on reload. Always use `firewall-cmd --ipset`
> for permanent changes.

---

↑ [Back to TOC](#table-of-contents)

## 11. IP Set XML Format

Full schema for IP set XML files (`/etc/firewalld/ipsets/`):

```xml
<?xml version="1.0" encoding="utf-8"?>
<ipset type="hash:ip|hash:net|hash:mac|...">
  <short>Display name</short>
  <description>Description of the set</description>

  <!-- Options -->
  <option name="family" value="inet"/>      <!-- inet=IPv4, inet6=IPv6 -->
  <option name="timeout" value="3600"/>     <!-- Default entry timeout in seconds -->
  <option name="maxelem" value="65536"/>    <!-- Maximum number of entries -->
  <option name="hashsize" value="1024"/>    <!-- Initial hash table size -->

  <!-- Entries -->
  <entry>192.168.1.100</entry>
  <entry>10.0.0.0/8</entry>               <!-- CIDR for hash:net -->
  <entry>aa:bb:cc:dd:ee:ff</entry>         <!-- MAC for hash:mac -->
</ipset>
```

---

↑ [Back to TOC](#table-of-contents)

## Lab 9 — Dynamic Block List with Auto-Expiry

**Topology:** Single-node (node1)

**Objective:** Create a dynamic blocklist IP set, add entries with timeouts,
bind it to a rich rule, watch entries expire, and observe how it maps to nftables.

---

### Step 1 — Start node1

```bash
# 🔧 LAB STEP (on host)
podman exec -it node1 bash
```

---

### Step 2 — Create the IP sets

```bash
# 🔧 LAB STEP (inside node1)

# Permanent blocklist (manual entries that persist)
firewall-cmd --permanent --new-ipset=perm-blocklist --type=hash:ip

# Temporary blocklist (auto-expiring entries, default 5 minutes)
firewall-cmd --permanent --new-ipset=temp-blocklist \
  --type=hash:ip \
  --option=timeout=300

# Allowlist (overrides blocklist)
firewall-cmd --permanent --new-ipset=allowlist --type=hash:ip

firewall-cmd --reload
```

---

### Step 3 — Add entries

```bash
# 🔧 LAB STEP (inside node1)

# Permanent block
firewall-cmd --permanent --ipset=perm-blocklist --add-entry=198.51.100.1
firewall-cmd --permanent --ipset=perm-blocklist --add-entry=198.51.100.2
firewall-cmd --reload

# Temporary blocks (runtime only, expire after 60 seconds for demo)
firewall-cmd --ipset=temp-blocklist --add-entry=203.0.113.10 --timeout=60
firewall-cmd --ipset=temp-blocklist --add-entry=203.0.113.11 --timeout=120

# Allowlist entry
firewall-cmd --permanent --ipset=allowlist --add-entry=172.20.1.1
firewall-cmd --reload
```

---

### Step 4 — Create rich rules using the sets

```bash
# 🔧 LAB STEP (inside node1)

# Highest priority: allowlist always gets through
firewall-cmd --permanent --zone=public --add-rich-rule='
  rule priority="-200" family="ipv4" source ipset="allowlist"
  service name="http"
  accept
'

# Second priority: permanent blocklist
firewall-cmd --permanent --zone=public --add-rich-rule='
  rule priority="-100" family="ipv4" source ipset="perm-blocklist"
  log prefix="PERM-BLOCKED: " level="warning" limit value="3/m"
  drop
'

# Third priority: temporary blocklist
firewall-cmd --permanent --zone=public --add-rich-rule='
  rule priority="-50" family="ipv4" source ipset="temp-blocklist"
  log prefix="TEMP-BLOCKED: " level="info" limit value="3/m"
  drop
'

firewall-cmd --reload

# Verify rules
firewall-cmd --list-rich-rules --zone=public
```

---

### Step 5 — Observe in nftables

```bash
# 🔧 LAB STEP (inside node1)

# See the sets
nft list sets

# See the perm-blocklist set with its entries
nft list set inet firewalld perm-blocklist

# See the temp-blocklist (should have timeout metadata)
nft list set inet firewalld temp-blocklist
```

---

### Step 6 — Watch temporary entries expire

```bash
# 🔧 LAB STEP (inside node1)

# Check current entries in temp-blocklist
firewall-cmd --ipset=temp-blocklist --get-entries

# Wait and check again (203.0.113.10 has 60s timeout)
echo "Waiting 65 seconds for first entry to expire..."
sleep 65

# Check again — 203.0.113.10 should be gone
firewall-cmd --ipset=temp-blocklist --get-entries

# After 120s total, 203.0.113.11 should also be gone
```

---

### Step 7 — Test the allowlist override

```bash
# 🔧 LAB STEP (inside node1)
# Add 172.20.1.1 to the permanent blocklist too
firewall-cmd --permanent --ipset=perm-blocklist --add-entry=172.20.1.1
firewall-cmd --reload

# Check rich rules — allowlist has priority -200, perm-blocklist has -100
# So allowlist rule should be evaluated first
firewall-cmd --list-rich-rules --zone=public | sort

# 172.20.1.1 is in BOTH allowlist and perm-blocklist
# Since allowlist rule has lower priority number (-200), it runs first
# Result: 172.20.1.1 GETS ACCESS
```

> **💡 CONCEPT CHECK**
> Priority numbers determine evaluation order: -200 runs before -100.
> When the allowlist rule (priority -200) matches 172.20.1.1, it accepts
> immediately and no further rules are checked — so the blocklist entry is
> never reached. This is the "first match wins" model.

---

### Step 8 — Script: automatic blocking on failed login

```bash
# 🔧 LAB STEP (inside node1)

# Create a simple auto-block script
cat > /usr/local/bin/auto-block.sh << 'SCRIPT'
#!/usr/bin/env bash
# Block an IP temporarily via the temp-blocklist set
IP="$1"
DURATION="${2:-3600}"  # Default 1 hour

if [[ -z "$IP" ]]; then
  echo "Usage: $0 <ip> [duration_seconds]"
  exit 1
fi

firewall-cmd --ipset=temp-blocklist --add-entry="$IP" --timeout="$DURATION"
logger -t auto-block "Blocked $IP for ${DURATION}s"
echo "Blocked $IP for ${DURATION}s"
SCRIPT
chmod +x /usr/local/bin/auto-block.sh

# Test it
/usr/local/bin/auto-block.sh 198.51.100.200 30
firewall-cmd --ipset=temp-blocklist --get-entries
```

---

### Step 9 — Clean up

```bash
# 🔧 LAB STEP (inside node1)

# Remove rich rules
firewall-cmd --permanent --zone=public --remove-rich-rule='
  rule priority="-200" family="ipv4" source ipset="allowlist"
  service name="http" accept
'
firewall-cmd --permanent --zone=public --remove-rich-rule='
  rule priority="-100" family="ipv4" source ipset="perm-blocklist"
  log prefix="PERM-BLOCKED: " level="warning" limit value="3/m" drop
'
firewall-cmd --permanent --zone=public --remove-rich-rule='
  rule priority="-50" family="ipv4" source ipset="temp-blocklist"
  log prefix="TEMP-BLOCKED: " level="info" limit value="3/m" drop
'

# Remove sets
firewall-cmd --permanent --delete-ipset=perm-blocklist
firewall-cmd --permanent --delete-ipset=temp-blocklist
firewall-cmd --permanent --delete-ipset=allowlist

firewall-cmd --reload
```

---

### Summary

| Feature | Command |
|---------|---------|
| Create set | `--permanent --new-ipset=name --type=hash:ip` |
| Create with default timeout | `--option=timeout=3600` |
| Add permanent entry | `--permanent --ipset=name --add-entry=IP` |
| Add timed entry | `--ipset=name --add-entry=IP --timeout=60` |
| Use in rich rule | `source ipset="name"` |
| Use as zone source | `--add-source=ipset:name` |
| View in nftables | `nft list set inet firewalld name` |

---

*Module 09 complete.*

**Continue to [Module 10 — Logging, Troubleshooting, and Debugging →](./10-logging-troubleshooting-and-debugging.md)**

---

© 2026 Jaco Steyn — Licensed under CC BY-SA 4.0

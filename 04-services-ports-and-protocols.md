# Module 04 — Services, Ports, and Protocols

> **Goal:** Master how firewalld models network access through named services,
> raw ports, port ranges, and protocol controls. Learn to create custom service
> definitions for your own applications, control ICMP behaviour, and understand
> how all of these map to nftables rules.

---

## Table of Contents

1. [1. Services vs Ports — Which Should You Use?](#1-services-vs-ports-which-should-you-use)
2. [2. Predefined Services](#2-predefined-services)
3. [3. Service XML Format](#3-service-xml-format)
4. [4. Managing Services on Zones](#4-managing-services-on-zones)
5. [5. Raw Port and Protocol Management](#5-raw-port-and-protocol-management)
6. [6. Creating Custom Services](#6-creating-custom-services)
7. [7. ICMP Types and ICMP Blocking](#7-icmp-types-and-icmp-blocking)
8. [8. ICMP Block Inversion](#8-icmp-block-inversion)
9. [9. Source Ports](#9-source-ports)
10. [10. Connection Tracking Helpers](#10-connection-tracking-helpers)
11. [Lab 4 — Custom Service for a Containerised App](#lab-4-custom-service-for-a-containerised-app)

---

↑ [Back to TOC](#table-of-contents)

## 1. Services vs Ports — Which Should You Use?

Both services and raw ports allow traffic through the firewall. The difference
is at the **level of abstraction**:

| Approach | Example | Advantage | Disadvantage |
|----------|---------|-----------|-------------|
| **Service name** | `--add-service=https` | Human-readable intent; self-documenting; easy to list/audit | Must create service definitions for custom apps |
| **Raw port** | `--add-port=443/tcp` | Simple; no service definition needed | Not self-documenting; what does port 8743 do? |

**Recommendation:** Use named services wherever possible. Create custom service
XML files for your applications. A list of service names in `--list-all` output
is far more readable and auditable than a list of port numbers.

Reserve raw ports for one-off, temporary rules during testing.

---

↑ [Back to TOC](#table-of-contents)

## 2. Predefined Services

RHEL 10 ships with hundreds of predefined service definitions. Browse them:

```bash
# List all service names
firewall-cmd --get-services

# Count them
firewall-cmd --get-services | tr ' ' '\n' | wc -l

# Get details of a specific service
firewall-cmd --info-service=http
firewall-cmd --info-service=dns
firewall-cmd --info-service=postgresql

# Find a service by browsing the service XML directory
ls /usr/lib/firewalld/services/ | grep -i postgres
```

### Inspecting a service definition

```bash
cat /usr/lib/firewalld/services/http.xml
```

```xml
<?xml version="1.0" encoding="utf-8"?>
<service>
  <short>WWW (HTTP)</short>
  <description>
    HTTP is the protocol used to serve Web pages. If you plan to
    make your Web server publicly available, enable this option.
    This option is not required for viewing pages locally or
    developing Web applications.
  </description>
  <port protocol="tcp" port="80"/>
</service>
```

A more complex service — `dns`:

```bash
cat /usr/lib/firewalld/services/dns.xml
```

```xml
<?xml version="1.0" encoding="utf-8"?>
<service>
  <short>DNS</short>
  <description>
    The Domain Name System (DNS) is used to provide and request
    host and domain names.
  </description>
  <port protocol="tcp" port="53"/>
  <port protocol="udp" port="53"/>
</service>
```

Note that `dns` includes both TCP/53 and UDP/53 — a single service name opens
both. This is the power of the abstraction: you don't need to remember which
protocol a service uses.

### A service with a connection tracking helper — `ftp`:

```bash
cat /usr/lib/firewalld/services/ftp.xml
```

```xml
<?xml version="1.0" encoding="utf-8"?>
<service>
  <short>FTP</short>
  <description>FTP is a protocol used for remote file transfer.</description>
  <port protocol="tcp" port="21"/>
  <helper name="ftp"/>
</service>
```

The `<helper name="ftp"/>` element tells firewalld to load the FTP connection
tracking helper. FTP passive mode opens a second TCP connection (the data
channel) on a dynamic port. Without the conntrack helper, the data connection
would be dropped because firewalld doesn't know it's part of an FTP session.
The helper instructs the kernel to track this secondary connection as RELATED
and allow it.

---

↑ [Back to TOC](#table-of-contents)

## 3. Service XML Format

The full schema for service XML files:

```xml
<?xml version="1.0" encoding="utf-8"?>
<service [version="..."]>
  <!-- Short display name -->
  <short>My Application</short>

  <!-- Human-readable description (shown in firewall-config and info commands) -->
  <description>
    My custom application uses port 9000/tcp for its API.
  </description>

  <!-- Ports this service requires -->
  <port protocol="tcp" port="9000"/>
  <port protocol="udp" port="9001"/>
  <port protocol="tcp" port="9100-9199"/>  <!-- port range -->

  <!-- Source ports (rare — see section 9) -->
  <source-port protocol="tcp" port="9000"/>

  <!-- Connection tracking helpers (for protocols with dynamic ports) -->
  <helper name="ftp"/>

  <!-- Modules to load (legacy — prefer helpers) -->
  <module name="nf_conntrack_ftp"/>

  <!-- Destination addresses (restrict service to specific targets) -->
  <destination ipv4="192.168.0.0/16"/>
  <destination ipv6="fe80::/10"/>
</service>
```

---

↑ [Back to TOC](#table-of-contents)

## 4. Managing Services on Zones

### Adding and removing services

```bash
# Add service (runtime)
firewall-cmd --zone=public --add-service=http

# Add service (permanent)
firewall-cmd --permanent --zone=public --add-service=http

# Add service (both in one go — run twice or use runtime-to-permanent)
firewall-cmd --permanent --zone=public --add-service=http
firewall-cmd --zone=public --add-service=http

# Remove service (runtime)
firewall-cmd --zone=public --remove-service=http

# Remove service (permanent)
firewall-cmd --permanent --zone=public --remove-service=http

# List services in a zone
firewall-cmd --zone=public --list-services

# Show full details of a service
firewall-cmd --info-service=http
```

### Timeout (temporary) service rules

Sometimes you need to allow a service temporarily — for testing, for a
scheduled maintenance window, or for incident response:

```bash
# Allow FTP for 60 seconds, then it disappears automatically
firewall-cmd --zone=public --add-service=ftp --timeout=60

# Allow with minutes
firewall-cmd --zone=public --add-service=http --timeout=5m

# Allow with hours
firewall-cmd --zone=public --add-service=http --timeout=2h
```

> **📝 NOTE — Timeouts are runtime only**
> `--timeout` cannot be combined with `--permanent`. Temporary rules only exist
> in the runtime state and expire automatically.

---

↑ [Back to TOC](#table-of-contents)

## 5. Raw Port and Protocol Management

### Adding and removing ports

```bash
# Add a single TCP port (runtime)
firewall-cmd --zone=public --add-port=8080/tcp

# Add a single UDP port (permanent)
firewall-cmd --permanent --zone=public --add-port=5353/udp

# Add a port range (runtime)
firewall-cmd --zone=public --add-port=6000-6100/tcp

# Remove a port
firewall-cmd --zone=public --remove-port=8080/tcp
firewall-cmd --permanent --zone=public --remove-port=8080/tcp

# List ports in a zone
firewall-cmd --zone=public --list-ports
```

### Protocols (non-port-based)

Some services don't use TCP or UDP ports — they use other IP protocols:

```bash
# Allow GRE (Generic Routing Encapsulation — used by many VPNs)
firewall-cmd --permanent --zone=public --add-protocol=gre

# Allow ESP (Encapsulating Security Payload — IPsec)
firewall-cmd --permanent --zone=public --add-protocol=esp

# Allow AH (Authentication Header — IPsec)
firewall-cmd --permanent --zone=public --add-protocol=ah

# List protocols
firewall-cmd --zone=public --list-protocols

# Remove a protocol
firewall-cmd --permanent --zone=public --remove-protocol=gre
```

Common IP protocol numbers:

| Protocol | Number | Use |
|----------|--------|-----|
| ICMP | 1 | Ping, error messages |
| TCP | 6 | Most applications |
| UDP | 17 | DNS, DHCP, streaming |
| GRE | 47 | VPN tunnels |
| ESP | 50 | IPsec encryption |
| AH | 51 | IPsec authentication |
| ICMPv6 | 58 | IPv6 neighbor discovery |
| SCTP | 132 | Telecom, high reliability |

---

↑ [Back to TOC](#table-of-contents)

## 6. Creating Custom Services

Custom services live in `/etc/firewalld/services/`. Once created, they are
available in `firewall-cmd --get-services` and can be used exactly like
predefined services.

### Step-by-step: Create a service for a custom app

Imagine you have a custom monitoring application that:
- Listens on TCP 9090 (metrics API)
- Listens on TCP 9091 (admin interface)
- Listens on UDP 9092 (UDP health check)

```bash
# Create the service XML
cat > /etc/firewalld/services/myapp.xml << 'EOF'
<?xml version="1.0" encoding="utf-8"?>
<service>
  <short>MyApp</short>
  <description>
    Custom monitoring application. Port 9090/tcp for metrics API,
    9091/tcp for admin, 9092/udp for health checks.
  </description>
  <port protocol="tcp" port="9090"/>
  <port protocol="tcp" port="9091"/>
  <port protocol="udp" port="9092"/>
</service>
EOF

# Reload firewalld to recognise the new service
firewall-cmd --reload

# Verify it appears
firewall-cmd --get-services | tr ' ' '\n' | grep myapp

# Get its details
firewall-cmd --info-service=myapp

# Use it like any service
firewall-cmd --permanent --zone=internal --add-service=myapp
firewall-cmd --reload
```

### Overriding a predefined service

To customise a predefined service (for example, SSH on a non-standard port),
copy the system file to `/etc/firewalld/services/` and modify it:

```bash
# Copy the predefined ssh service
cp /usr/lib/firewalld/services/ssh.xml /etc/firewalld/services/ssh.xml

# Edit it to use port 2222 instead of 22
# (edit /etc/firewalld/services/ssh.xml)
sed -i 's/port="22"/port="2222"/' /etc/firewalld/services/ssh.xml

# Reload
firewall-cmd --reload

# Now the 'ssh' service means port 2222
firewall-cmd --info-service=ssh
```

> **⚠️  IMPORTANT — Overriding vs creating**
> Overriding a predefined service (copying it to /etc/firewalld/services/) is
> tempting but risky — it changes the meaning of the service *globally*. All
> zones that allow `ssh` will now allow port 2222 instead of 22. Often it's
> cleaner to create a new service (e.g., `ssh-custom`) and add it instead of
> overriding the standard one.

---

↑ [Back to TOC](#table-of-contents)

## 7. ICMP Types and ICMP Blocking

ICMP (Internet Control Message Protocol) is used for:
- **Echo request/reply** — ping
- **Destination unreachable** — "no route to host", "port unreachable"
- **Time exceeded** — traceroute, TTL expiry
- **Redirect** — routing optimisation
- **Parameter problem** — malformed IP header

firewalld can block specific ICMP types, which is useful for stealth hardening
or reducing attack surface.

### Listing available ICMP types

```bash
# All defined ICMP types
firewall-cmd --get-icmptypes

# Details of a specific type
firewall-cmd --info-icmptype=echo-request
```

### Blocking ICMP types

```bash
# Block ping (make the host invisible to ping sweeps)
firewall-cmd --permanent --zone=public --add-icmp-block=echo-request

# Block IPv6 ping
firewall-cmd --permanent --zone=public --add-icmp-block=echo-request  # applies to both

# List blocked ICMP types
firewall-cmd --zone=public --list-icmp-blocks

# Remove an ICMP block
firewall-cmd --permanent --zone=public --remove-icmp-block=echo-request
```

### ICMP types reference

| Type | Name | Used for |
|------|------|---------|
| `echo-request` | Ping request | Host discovery (block for stealth) |
| `echo-reply` | Ping reply | Responses to ping |
| `destination-unreachable` | Unreachable | Error notification (don't block this) |
| `time-exceeded` | TTL expired | Traceroute (block to hide network topology) |
| `router-solicitation` | RS | IPv6 neighbour discovery (don't block) |
| `router-advertisement` | RA | IPv6 default gateway (don't block) |
| `redirect` | Redirect | ICMP redirect (often blocked as attack vector) |
| `timestamp-request` | Timestamp | Timing attack vector (often blocked) |

> **⚠️  IMPORTANT — Don't block destination-unreachable**
> Blocking `destination-unreachable` breaks TCP's PMTU (Path MTU Discovery),
> which relies on ICMP "fragmentation needed" messages. This causes mysterious
> connection hangs, especially for VPNs and tunnels. Never block this type
> without a very specific reason.

---

↑ [Back to TOC](#table-of-contents)

## 8. ICMP Block Inversion

Normally, an ICMP block list is an **allowlist exception**: all ICMP is allowed
except the listed types. ICMP block inversion **reverses the logic**: all ICMP
is **blocked** except the listed types.

```bash
# Enable ICMP block inversion (block ALL ICMP by default)
firewall-cmd --permanent --zone=public --add-icmp-block-inversion

# Now add the types you WANT to allow (whitelist)
firewall-cmd --permanent --zone=public --add-icmp-block=echo-request      # block ping specifically
firewall-cmd --permanent --zone=public --add-icmp-block=timestamp-request # block timestamp

# With inversion active, "adding a block" means "allow this type"
# Anything NOT in the list is dropped

# Check status
firewall-cmd --zone=public --query-icmp-block-inversion

# Remove inversion
firewall-cmd --permanent --zone=public --remove-icmp-block-inversion
```

> **💡 When to use ICMP block inversion**
> ICMP block inversion makes sense on the most restrictive zones (`public`,
> `dmz`) where you want to allow only specific ICMP types (typically
> `destination-unreachable` for PMTU) and block everything else. For less
> restrictive zones, the default (allow ICMP, optionally block specific types)
> is more manageable.

---

↑ [Back to TOC](#table-of-contents)

## 9. Source Ports

Most firewall rules match on **destination port** — what service the packet
is heading to. Occasionally you need to match on **source port** — where the
packet claims to have come from.

Source port filtering is rare but has specific use cases:
- Allow traffic that originates from privileged ports (< 1024) only —
  classic Unix RPC security model
- Rate-limit traffic from specific source ports
- Allow DNS replies (which come from source port 53)

```bash
# Allow traffic originating from source port 53 (DNS responses)
firewall-cmd --permanent --zone=public --add-source-port=53/udp

# In a service definition:
# <source-port protocol="udp" port="53"/>

# List source ports
firewall-cmd --zone=public --list-source-ports

# Remove
firewall-cmd --permanent --zone=public --remove-source-port=53/udp
```

---

↑ [Back to TOC](#table-of-contents)

## 10. Connection Tracking Helpers

Some application protocols establish secondary connections on dynamically
negotiated ports. The kernel's conntrack module has **helpers** that understand
these protocols and mark the secondary connections as `RELATED`, ensuring they
are allowed through the firewall.

Common protocols needing helpers:

| Protocol | Helper | Why needed |
|----------|--------|------------|
| FTP (active/passive) | `ftp` | Data channel port negotiated dynamically |
| SIP | `sip` | Voice/video RTP streams on negotiated ports |
| TFTP | `tftp` | UDP data transfer on dynamic port |
| H.323 | `h323` | Video conferencing signalling |
| PPTP | `pptp` | VPN control channel |

### Loading helpers via services

The cleanest way to use helpers is via service definitions:

```bash
# The ftp service includes the ftp helper automatically
firewall-cmd --permanent --zone=public --add-service=ftp

# Verify helper is loaded
cat /usr/lib/firewalld/services/ftp.xml
# <helper name="ftp"/>
```

### Checking available helpers

```bash
# List all available helpers
firewall-cmd --get-helpers

# Get details
firewall-cmd --info-helper=ftp
```

### Adding helpers directly to zones

```bash
# Add a helper directly to a zone (without using a service)
firewall-cmd --permanent --zone=internal --add-helper=ftp
firewall-cmd --reload

# List helpers in a zone
firewall-cmd --zone=internal --list-helpers
```

> **📝 NOTE — Helper security considerations**
> Connection tracking helpers inspect packet payload to find dynamically
> negotiated ports. This is a form of deep packet inspection. In strict
> security environments, helpers may be disabled by default on the kernel and
> need explicit enabling. On RHEL 10, helpers are generally available but some
> require `nf_conntrack_<protocol>` kernel modules.

---

↑ [Back to TOC](#table-of-contents)

## Lab 4 — Custom Service for a Containerised App

**Topology:** Single-node (node1 only)

**Objective:** Deploy a simple web server container on node1, create a custom
firewalld service definition for it, expose it correctly, and verify port-level
access control — then show how the nftables rules look.

---

### Step 1 — Start node1 and open a shell

```bash
# 🔧 LAB STEP (on host)
podman exec -it node1 bash || (
  podman start node1 2>/dev/null || \
  podman run -d --name node1 --hostname node1 \
    --network labnet-external:ip=172.20.1.10 \
    --cap-add NET_ADMIN --cap-add SYS_ADMIN --cap-add NET_RAW \
    --security-opt label=disable \
    --tmpfs /tmp --tmpfs /run --tmpfs /run/lock \
    -v /sys/fs/cgroup:/sys/fs/cgroup:ro firewalld-lab
  sleep 5
  podman exec -it node1 bash
)
```

---

### Step 2 — Start a simple web server on non-standard ports

```bash
# 🔧 LAB STEP (inside node1)

# Start a simple HTTP server on port 8080 (API) and 9090 (admin)
python3 -m http.server 8080 &
python3 -m http.server 9090 &

# Verify they are listening
ss -tlnp | grep python
```

---

### Step 3 — Create the custom service definition

```bash
# 🔧 LAB STEP (inside node1)

cat > /etc/firewalld/services/labapp.xml << 'EOF'
<?xml version="1.0" encoding="utf-8"?>
<service>
  <short>Lab Application</short>
  <description>
    Lab demonstration application. Port 8080/tcp is the public API.
    Port 9090/tcp is the restricted admin interface.
  </description>
  <port protocol="tcp" port="8080"/>
  <port protocol="tcp" port="9090"/>
</service>
EOF

# Reload to pick up new service
firewall-cmd --reload

# Verify
firewall-cmd --info-service=labapp
```

---

### Step 4 — Test without adding the service (should be blocked)

```bash
# 🔧 LAB STEP (from host — outside the container)

# Try to reach port 8080 on node1 from the host
curl -m 3 http://172.20.1.10:8080/
# Should fail — firewalld is blocking it
```

---

### Step 5 — Add only the public API port (8080)

```bash
# 🔧 LAB STEP (inside node1)

# Don't add the full service yet — just port 8080
firewall-cmd --zone=public --add-port=8080/tcp

# Verify
firewall-cmd --list-ports --zone=public
```

```bash
# From host:
curl -m 3 http://172.20.1.10:8080/
# Should now return an HTML directory listing
```

---

### Step 6 — Verify admin port (9090) is still blocked

```bash
# 🔧 LAB STEP (from host)
curl -m 3 http://172.20.1.10:9090/
# Should still fail
```

---

### Step 7 — Replace the raw port with the service definition

```bash
# 🔧 LAB STEP (inside node1)

# Remove the raw port
firewall-cmd --zone=public --remove-port=8080/tcp

# Add the service (which includes both ports)
firewall-cmd --zone=public --add-service=labapp

# List what's now allowed
firewall-cmd --list-all --zone=public
```

---

### Step 8 — Verify both ports are now accessible

```bash
# 🔧 LAB STEP (from host)
curl -m 3 http://172.20.1.10:8080/
# Success

curl -m 3 http://172.20.1.10:9090/
# Also success — both ports in the service are allowed
```

---

### Step 9 — Inspect nftables rules

```bash
# 🔧 LAB STEP (inside node1)

# See how the labapp service appears in nftables
nft list chain inet firewalld filter_IN_public | grep -E "8080|9090"
```

Expected output:
```
tcp dport 8080 accept
tcp dport 9090 accept
```

> **💡 CONCEPT CHECK**
> Notice that the nftables rule does not know about the `labapp` service name —
> it only knows about port numbers. The service name is a firewalld abstraction.
> nftables just sees ports. This is why `nft list ruleset` alone doesn't tell
> you the *intent* of a rule — you need `firewall-cmd --list-all` for that.

---

### Step 10 — Block ICMP ping in the public zone

```bash
# 🔧 LAB STEP (inside node1)

# Test ping works currently
# (from host)
ping -c 2 172.20.1.10

# Block ping
firewall-cmd --zone=public --add-icmp-block=echo-request

# Test ping again — should time out or get blocked
# ping -c 2 172.20.1.10

# Verify ICMP block is set
firewall-cmd --list-icmp-blocks --zone=public

# See it in nftables
nft list chain inet firewalld filter_IN_public | grep icmp

# Remove the block
firewall-cmd --zone=public --remove-icmp-block=echo-request
```

---

### Step 11 — Clean up

```bash
# 🔧 LAB STEP (inside node1)
firewall-cmd --zone=public --remove-service=labapp
kill $(pgrep -f "python3 -m http.server") 2>/dev/null
rm /etc/firewalld/services/labapp.xml
firewall-cmd --reload
```

---

### Summary

You learned:

1. Services are named bundles of ports — more readable and auditable than raw ports
2. Custom service XML files go in `/etc/firewalld/services/`
3. A service can include multiple ports, multiple protocols, and conntrack helpers
4. ICMP types can be individually blocked per zone
5. nftables rules only see port numbers — service names are a firewalld layer

---

*Module 04 complete.*

**Continue to [Module 05 — Policies and Inter-Zone Routing →](./05-policies-and-inter-zone-routing.md)**

---

© 2026 Jaco Steyn — Licensed under CC BY-SA 4.0

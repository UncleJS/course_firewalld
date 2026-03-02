# Module 08 — Container Integration
[![CC BY-NC-SA 4.0](https://img.shields.io/badge/License-CC%20BY--NC--SA%204.0-lightgrey)](./LICENSE.md)
[![RHEL 10](https://img.shields.io/badge/platform-RHEL%2010-red)](https://access.redhat.com/products/red-hat-enterprise-linux)
[![firewalld](https://img.shields.io/badge/firewalld-RHEL%2010-orange)](https://access.redhat.com/products/red-hat-enterprise-linux)

> **Goal:** Understand how Podman and Docker interact with firewalld on RHEL 10.
> Master the seamless and strict integration modes, know how to own firewall
> rules for containers rather than letting the container runtime manage them,
> and understand the significant differences between rootless and rootful
> Podman networking.

---

## Table of Contents

1. [1. The Container-Firewall Problem](#1-the-container-firewall-problem)
2. [2. How Podman Networking Works on RHEL 10](#2-how-podman-networking-works-on-rhel-10)
3. [3. Rootless vs Rootful Podman and Firewalld](#3-rootless-vs-rootful-podman-and-firewalld)
4. [4. Seamless Mode (Default): StrictForwardPorts=no](#4-seamless-mode-default-strictforwardportsno)
5. [5. Strict Mode: StrictForwardPorts=yes](#5-strict-mode-strictforwardportsyes)
6. [6. Binding Container Networks to Zones](#6-binding-container-networks-to-zones)
7. [7. Container-to-Host Traffic Policies](#7-container-to-host-traffic-policies)
8. [8. Container-to-Container Cross-Network Policies](#8-container-to-container-cross-network-policies)
9. [9. Disabling Container Runtime Firewall Management](#9-disabling-container-runtime-firewall-management)
10. [10. Practical Container Zone Architecture](#10-practical-container-zone-architecture)
11. [Lab 8 — Seamless vs Strict Mode Comparison](#lab-8-seamless-vs-strict-mode-comparison)

---

↑ [Back to TOC](#table-of-contents)

## 1. The Container-Firewall Problem

When you run a container with a published port:

```bash
podman run -d -p 8080:80 nginx
```

Something happens to your firewall rules. The container runtime adds DNAT rules
to redirect incoming traffic on port 8080 to the container's port 80. On RHEL 10
with Podman 5.x and Netavark, these rules appear in nftables.

The fundamental tension is:
- **Container runtime perspective:** "I should manage the NAT rules needed for
  my containers to work."
- **Security operations perspective:** "The firewall should be under explicit
  administrative control — no service should silently modify firewall rules."

Both perspectives are valid. firewalld 2.x on RHEL 10 gives you control over
which perspective wins, via `StrictForwardPorts`.

---

↑ [Back to TOC](#table-of-contents)

## 2. How Podman Networking Works on RHEL 10

RHEL 10 ships with Podman 5.x, which uses the **Netavark** network stack
(replacing the older CNI plugin model from Podman 4.x).

### Netavark architecture

```
Podman CLI
    │
    ▼
Netavark (network configuration daemon)
    │
    ├── Creates/manages bridge interfaces (e.g., podman0, podmanN)
    ├── Configures container network namespaces
    ├── Manages nftables rules for NAT and filtering
    └── Uses Aardvark-dns for container DNS resolution
```

### Network types

**Bridge network (default for rootful)**

```bash
# Default podman network uses a bridge
podman network inspect podman
# Shows: driver=bridge, subnet=10.88.0.0/16
```

A bridge interface (`cni-podman0` or similar) is created on the host. Containers
connect to it. The bridge is in a specific firewalld zone (by default `public` or
it gets the default zone).

**Slirp4netns (rootless, older)**

Rootless containers on RHEL 9 / Podman 4.x used `slirp4netns` — a userspace
TCP/IP stack that requires no kernel privileges. Traffic is tunnelled through
a socket. This meant rootless containers had NO impact on host firewall rules
because all networking was in userspace.

**Pasta (rootless, RHEL 10 / Podman 5.x)**

RHEL 10 uses `pasta` (also called `passt`) for rootless container networking.
Pasta is more performant than slirp4netns and supports host network integration
better, but still operates without kernel privileges for the most part.

> **📝 NOTE — Rootless firewall impact**
> With pasta-based networking, rootless containers generally do NOT add rules to
> the host firewall. Published ports are handled in userspace. This is different
> from rootful containers, which DO modify nftables.

---

↑ [Back to TOC](#table-of-contents)

## 3. Rootless vs Rootful Podman and Firewalld

This is one of the most important distinctions in RHEL 10 container networking:

### Rootful Podman (`sudo podman` or `podman` as root)

```
podman run -p 8080:80 nginx   (as root)

nftables effect:
- Adds DNAT rule in prerouting: tcp dport 8080 dnat to 172.17.0.2:80
- Adds masquerade rule for container network
- Creates forward rules for container traffic
- These are real kernel firewall rules visible to firewalld
```

Rootful containers DO affect nftables. `StrictForwardPorts` applies here.

### Rootless Podman (`podman` as regular user)

```
podman run -p 8080:80 nginx   (as regular user)

nftables effect:
- Pasta/slirp4netns handles port binding in userspace
- Published port 8080 is bound to the user process (pasta)
- No nftables DNAT rules are added to the kernel firewall
- The host firewall doesn't see individual container connections
```

Rootless containers generally do NOT affect nftables.

**Implication for our course labs:** The lab containers themselves run with
`--cap-add NET_ADMIN` and manipulate nftables inside their own network namespaces.
When we run containers *inside* our lab nodes with rootless podman, those
containers use pasta-based networking.

### A hybrid approach: iptables-to-nftables bridge

Some container tools (older Docker, or Podman with `--rootful` on systems without
full nftables support) use `iptables-nft` — which translates iptables commands
to nftables rules. On RHEL 10, this is less common but still possible.

---

↑ [Back to TOC](#table-of-contents)

## 4. Seamless Mode (Default): StrictForwardPorts=no

In seamless mode, container runtimes manage their own firewall rules and they
work independently of firewalld zone configuration.

```ini
# /etc/firewalld/firewalld.conf
StrictForwardPorts=no
```

### What this means in practice

1. You run: `podman run -p 8080:80 nginx` (rootful)
2. Netavark adds to nftables:
   ```
   tcp dport 8080 dnat to 172.17.0.2:80
   ```
3. External traffic to port 8080 is forwarded to the container
4. This happens even if your firewalld `public` zone doesn't have port 8080 open
5. `firewall-cmd --list-all` does NOT show port 8080 in the zone config

**Why it "bypasses" firewalld:**
The container's DNAT rules are in a separate nftables chain with a higher
priority than firewalld's forward filtering chain. firewalld's FORWARD rules
check if the forwarded destination is allowed, but in seamless mode, the
already-forwarded container traffic is implicitly accepted.

### Viewing container rules in nftables

```bash
# Rootful container published port appears here
nft list table ip filter  # or
nft list table ip nat      # for DNAT rules
```

---

↑ [Back to TOC](#table-of-contents)

## 5. Strict Mode: StrictForwardPorts=yes

In strict mode, firewalld controls all forwarding. Container-published ports
require explicit firewalld forward-port rules.

```bash
# Enable strict mode
sed -i 's/^StrictForwardPorts=.*/StrictForwardPorts=yes/' /etc/firewalld/firewalld.conf
# Or add if not present:
echo "StrictForwardPorts=yes" >> /etc/firewalld/firewalld.conf

firewall-cmd --reload
```

### What this means in practice

1. Container publishes port 8080 (adds its DNAT rule)
2. External client connects to port 8080
3. DNAT rule fires: packet redirected to 172.17.0.2:80
4. **firewalld's forward check:** Is this forwarded traffic allowed?
5. No explicit forward-port rule in firewalld → **BLOCKED**

### Allowing a container port in strict mode

```bash
# Get the container's IP
podman inspect my_container --format '{{.NetworkSettings.IPAddress}}'
# e.g., 172.17.0.2

# Add explicit forward-port rule
firewall-cmd --permanent --zone=public \
  --add-forward-port=port=8080:proto=tcp:toport=80:toaddr=172.17.0.2

firewall-cmd --reload

# Now the container is reachable
```

### Why use strict mode?

1. **Audit trail:** All open ports are visible in `firewall-cmd --list-all`
2. **Least privilege:** Containers only get access you explicitly grant
3. **Operator control:** Container runtime can't accidentally expose ports
4. **Compliance:** Some security frameworks require explicit firewall rules for
   all open ports

---

↑ [Back to TOC](#table-of-contents)

## 6. Binding Container Networks to Zones

To apply zone-level rules to container traffic, bind the container network's
bridge interface or CIDR to a firewalld zone.

### Binding a container bridge interface to a zone

```bash
# Find the bridge interface for the container network
podman network inspect mynet --format '{{.NetworkInterface}}'
# e.g., podman1

# Bind it to a zone
firewall-cmd --permanent --zone=internal --add-interface=podman1
firewall-cmd --reload

# Now all traffic from containers on 'mynet' is subject to internal zone rules
```

### Binding a container network CIDR to a zone

More reliable than interface binding (bridge names can change):

```bash
# Find the container network subnet
podman network inspect mynet --format '{{range .Subnets}}{{.Subnet}}{{end}}'
# e.g., 172.20.10.0/24

# Bind the subnet to a zone
firewall-cmd --permanent --zone=internal --add-source=172.20.10.0/24
firewall-cmd --reload

# All traffic FROM containers (as source) is treated as internal zone
```

### Creating a dedicated container zone

For better organisation, create a zone specifically for container traffic:

```bash
firewall-cmd --permanent --new-zone=containers
firewall-cmd --permanent --zone=containers --set-target=REJECT

# Allow only what containers need
firewall-cmd --permanent --zone=containers --add-service=http
firewall-cmd --permanent --zone=containers --add-service=https
firewall-cmd --permanent --zone=containers --add-service=dns

# Bind all container networks
firewall-cmd --permanent --zone=containers --add-source=172.17.0.0/16  # podman default
firewall-cmd --permanent --zone=containers --add-source=10.88.0.0/16   # podman default v2

firewall-cmd --reload
```

---

↑ [Back to TOC](#table-of-contents)

## 7. Container-to-Host Traffic Policies

Containers often need to reach services on the host (database, message queue,
APIs). Use policies with the `HOST` pseudo-zone.

### Allow containers to reach a specific host service

```bash
# Allow containers (internal zone) to reach the host's API on port 9000
firewall-cmd --permanent --new-policy containers_to_host
firewall-cmd --permanent --policy containers_to_host \
  --add-ingress-zone internal \
  --add-egress-zone HOST
firewall-cmd --permanent --policy containers_to_host --set-target REJECT
firewall-cmd --permanent --policy containers_to_host \
  --add-port 9000/tcp
firewall-cmd --reload
```

### Allow host to reach container (management/monitoring)

```bash
# Host can reach all container ports (for monitoring)
firewall-cmd --permanent --new-policy host_to_containers
firewall-cmd --permanent --policy host_to_containers \
  --add-ingress-zone HOST \
  --add-egress-zone internal
firewall-cmd --permanent --policy host_to_containers --set-target ACCEPT
firewall-cmd --reload
```

---

↑ [Back to TOC](#table-of-contents)

## 8. Container-to-Container Cross-Network Policies

By default, containers on different Podman networks cannot communicate with each
other. Use policies to enable specific cross-network traffic.

```bash
# Create two container networks
podman network create --subnet 172.20.10.0/24 net-frontend
podman network create --subnet 172.20.11.0/24 net-backend

# Bind to zones
firewall-cmd --permanent --new-zone=zone-frontend
firewall-cmd --permanent --zone=zone-frontend --add-source=172.20.10.0/24

firewall-cmd --permanent --new-zone=zone-backend
firewall-cmd --permanent --zone=zone-backend --add-source=172.20.11.0/24

# Allow frontend → backend on port 5432 (PostgreSQL)
firewall-cmd --permanent --new-policy frontend_to_backend
firewall-cmd --permanent --policy frontend_to_backend \
  --add-ingress-zone zone-frontend \
  --add-egress-zone zone-backend
firewall-cmd --permanent --policy frontend_to_backend --set-target REJECT
firewall-cmd --permanent --policy frontend_to_backend --add-port 5432/tcp

firewall-cmd --reload
```

---

↑ [Back to TOC](#table-of-contents)

## 9. Disabling Container Runtime Firewall Management

For maximum firewalld control, disable the container runtime's ability to
manage firewall rules.

### Podman 5.x with Netavark

Configure Netavark to not manage firewall rules by setting the firewall driver
to `none` in the network configuration:

```bash
# In containers.conf or network-specific configuration:
cat >> /etc/containers/containers.conf << 'EOF'
[network]
firewall_driver = "none"
EOF
```

Or per-network:

```bash
# NOTE: The com.docker.network.bridge.* options below are Docker-specific
# label keys and are NOT recognised by Podman/Netavark on RHEL 10.
# On RHEL 10, use containers.conf (firewall_driver = "none") shown above,
# or manage nftables rules manually after creating the network without these flags.
podman network create \
  --opt com.docker.network.bridge.enable_icc=false \
  --opt com.docker.network.bridge.enable_ip_masquerade=false \
  isolated-net
```

### Docker

```json
// /etc/docker/daemon.json
{
  "iptables": false
}
```

> **⚠️  IMPORTANT — Disabling runtime firewall management**
> When you disable the runtime's firewall management, containers can still
> run but:
> 1. Published ports (`-p`) won't work until you add explicit DNAT rules via
>    firewalld
> 2. Container-to-internet traffic won't work until you add masquerade rules
>    for the container network
>
> This is the "strict ownership" model — you get complete control but must
> configure everything explicitly.

---

↑ [Back to TOC](#table-of-contents)

## 10. Practical Container Zone Architecture

### Recommended architecture for a RHEL 10 production server running containers

```
┌──────────────────────────────────────────────────────────────┐
│                      RHEL 10 Host                            │
│                                                              │
│  Zone: public (eth0 — external)                              │
│  ├── Services: ssh (from management IPs only via rich rule)  │
│  └── Port forwarding: :443 → container:443                   │
│                                                              │
│  Zone: containers (podman bridge — container traffic source) │
│  ├── Services: none by default (restrictive)                 │
│  └── Policy: containers → HOST: allow 5432 (postgres)        │
│                                                              │
│  Zone: trusted (lo — loopback)                               │
│  └── Everything allowed                                      │
│                                                              │
│  Policy: containers → public (outbound NAT)                  │
│  └── Target: ACCEPT + masquerade                             │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### Implementation

```bash
# 1. Bind loopback to trusted
firewall-cmd --permanent --zone=trusted --add-interface=lo

# 2. Create container zone
firewall-cmd --permanent --new-zone=containers
firewall-cmd --permanent --zone=containers --set-target=REJECT
firewall-cmd --permanent --zone=containers --add-source=172.17.0.0/16

# 3. Allow containers to reach internet (with masquerade)
firewall-cmd --permanent --new-policy containers_outbound
firewall-cmd --permanent --policy containers_outbound \
  --add-ingress-zone containers \
  --add-egress-zone public
firewall-cmd --permanent --policy containers_outbound --set-target ACCEPT
firewall-cmd --permanent --policy containers_outbound --add-masquerade

# 4. Allow containers to reach host postgres
firewall-cmd --permanent --new-policy containers_to_host_db
firewall-cmd --permanent --policy containers_to_host_db \
  --add-ingress-zone containers \
  --add-egress-zone HOST
firewall-cmd --permanent --policy containers_to_host_db --set-target REJECT
firewall-cmd --permanent --policy containers_to_host_db --add-port 5432/tcp

# 5. Forward external HTTPS to container
firewall-cmd --permanent --zone=public \
  --add-forward-port=port=443:proto=tcp:toport=443:toaddr=172.17.0.2

# 6. SSH only from management subnet
firewall-cmd --permanent --zone=public --remove-service=ssh
firewall-cmd --permanent --zone=public --add-rich-rule='
  rule priority="-100" family="ipv4"
  source address="10.100.0.0/24"
  service name="ssh"
  accept
'

firewall-cmd --reload
```

---

↑ [Back to TOC](#table-of-contents)

## Lab 8 — Seamless vs Strict Mode Comparison

**Topology:** Single-node (node1 with rootful container inside)

**Objective:** Run a web server container inside node1 with a published port.
Observe its behaviour in seamless mode, then switch to strict mode and see the
difference. Use `nft list ruleset` to observe what the container runtime adds.

---

### Step 1 — Start node1

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

### Step 2 — Verify StrictForwardPorts is off (default)

```bash
# 🔧 LAB STEP (inside node1)
grep StrictForwardPorts /etc/firewalld/firewalld.conf || echo "Not set (default=no)"
```

---

### Step 3 — Run a web server and note the port is NOT in firewalld config

```bash
# 🔧 LAB STEP (inside node1)
# Start a simple web server (simulating a container-published port)
python3 -m http.server 9000 &

# Check firewalld — port 9000 is NOT listed
firewall-cmd --list-ports --zone=public

# But test access from host
# (Open another terminal on host)
curl -m 3 http://172.20.1.10:9000/
# With firewalld default zone having target=default (reject for unlisted),
# this should be BLOCKED
```

> **📝 NOTE**
> Our simulated scenario uses python3 directly, not a container runtime.
> In a real rootful container scenario, Netavark would add a DNAT rule.
> Here we're showing the firewalld zone rules control access.

---

### Step 4 — Explicitly allow the port and observe

```bash
# 🔧 LAB STEP (inside node1)
firewall-cmd --zone=public --add-port=9000/tcp

# Now test from host
# curl -m 3 http://172.20.1.10:9000/
# Should succeed

# List what's open
firewall-cmd --list-all --zone=public

# See the nftables rule
nft list chain inet firewalld filter_IN_public | grep 9000
```

---

### Step 5 — Observe nftables in seamless mode

```bash
# 🔧 LAB STEP (inside node1)
# View the full nftables ruleset to understand the structure
nft list ruleset

# Note which tables exist
nft list tables

# In a real container scenario with rootful Podman, you'd see additional
# tables from Netavark here. In our lab, only firewalld's tables are present.
```

---

### Step 6 — Enable strict mode and test

```bash
# 🔧 LAB STEP (inside node1)

# Enable strict mode
sed -i 's/StrictForwardPorts=no/StrictForwardPorts=yes/' /etc/firewalld/firewalld.conf
# If not set, add it:
grep -q StrictForwardPorts /etc/firewalld/firewalld.conf || \
  echo "StrictForwardPorts=yes" >> /etc/firewalld/firewalld.conf

# Reload
firewall-cmd --reload

# Verify
grep StrictForwardPorts /etc/firewalld/firewalld.conf
```

---

### Step 7 — Test that explicit rules still work

```bash
# 🔧 LAB STEP (inside node1)
# The port=9000 rule we added earlier is still there
firewall-cmd --list-ports --zone=public

# Access should still work (because we have an explicit zone rule)
# curl -m 3 http://172.20.1.10:9000/
```

---

### Step 8 — Bind container network CIDR to a zone

```bash
# 🔧 LAB STEP (inside node1)

# Simulate a container network CIDR (172.20.50.0/24)
firewall-cmd --permanent --new-zone=mycontainers 2>/dev/null || true
firewall-cmd --permanent --zone=mycontainers --set-target=REJECT
  firewall-cmd --permanent --zone=mycontainers --add-source=172.20.50.0/24 2>/dev/null || true

# Add DNS access for containers
firewall-cmd --permanent --zone=mycontainers --add-service=dns
firewall-cmd --permanent --zone=mycontainers --add-service=http

firewall-cmd --reload

# Verify
firewall-cmd --info-zone=mycontainers
```

---

### Step 9 — Reset strict mode and clean up

```bash
# 🔧 LAB STEP (inside node1)
sed -i 's/StrictForwardPorts=yes/StrictForwardPorts=no/' /etc/firewalld/firewalld.conf
firewall-cmd --reload
kill $(pgrep -f "python3 -m http.server") 2>/dev/null || true
```

---

### Summary

| Scenario | StrictForwardPorts | Result |
|----------|-------------------|--------|
| Container publishes port, no firewalld rule | `no` (default) | Port accessible |
| Container publishes port, no firewalld rule | `yes` | Port blocked |
| Container publishes port, explicit forward-port rule | `yes` | Port accessible |
| Rootless container (pasta networking) | Either | Port accessible (userspace NAT) |

Key takeaway: **rootless containers bypass host firewall rules** via userspace
networking. Only rootful containers interact with the host nftables rules.

---

*Module 08 complete.*

**Continue to [Module 09 — IP Sets and Dynamic Filtering →](./09-ipsets-and-dynamic-filtering.md)**

---

© 2026 UncleJS — Licensed under CC BY-NC-SA 4.0

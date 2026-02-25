# Module 00 — Lab Environment Setup

> **Goal:** Build a repeatable, rootless Podman-based lab on RHEL 10 that every
> subsequent module's exercises run inside. By the end of this module you will
> have one-, two-, and three-node container topologies running systemd and
> firewalld, ready to use.

---

## Table of Contents

1. [1. Why Containers as Lab Nodes?](#1-why-containers-as-lab-nodes)
2. [2. Host Requirements](#2-host-requirements)
3. [3. How the Lab Works](#3-how-the-lab-works)
4. [4. Building the Lab Container Image](#4-building-the-lab-container-image)
5. [5. Podman Networks — Lab Topology](#5-podman-networks-lab-topology)
6. [6. Starting Lab Nodes](#6-starting-lab-nodes)
7. [7. Helper Scripts](#7-helper-scripts)
8. [8. Verifying firewalld Inside a Node](#8-verifying-firewalld-inside-a-node)
9. [9. Topology Reference Table](#9-topology-reference-table)
10. [Lab 0 — Spin Up and Verify](#lab-0-spin-up-and-verify)
11. [Teardown and Reset](#teardown-and-reset)
12. [Troubleshooting the Lab Setup](#troubleshooting-the-lab-setup)

---

↑ [Back to TOC](#table-of-contents)

## 1. Why Containers as Lab Nodes?

A firewalld course needs nodes where you can freely manipulate the firewall,
break things, and reset without affecting your workstation. Traditionally that
meant virtual machines. Containers offer the same isolation at a fraction of the
resource cost, and on RHEL 10 rootless Podman is first-class infrastructure.

Using containers as lab nodes has several advantages for this course:

- **Speed** — a container starts in under a second; a VM takes minutes
- **Isolation** — each container has its own network namespace, so firewall
  rules inside the container do not affect your host
- **Reproducibility** — destroy and recreate a node in one command
- **Relevance** — RHEL 10 is a container-first OS; running containers *is* the
  skill, not just a convenience

The trade-off is that a container shares the host kernel. This means some kernel
features (notably loading kernel modules) require the host to already have them
loaded. In practice, all nftables and netfilter functionality we need is present
in any modern RHEL/Fedora/CentOS Stream 10 kernel.

---

↑ [Back to TOC](#table-of-contents)

## 2. Host Requirements

| Requirement | Minimum | Recommended |
|-------------|---------|-------------|
| OS | RHEL 9, RHEL 10, Fedora 39+, CentOS Stream 9+ | RHEL 10 |
| Podman | 4.0+ | 5.0+ |
| RAM | 2 GB free | 4 GB free |
| Disk | 2 GB free | 5 GB free |
| Kernel | 5.15+ | 6.6+ |
| User namespaces | Enabled | Enabled |

### Check host prerequisites

```bash
# Podman version
podman --version

# User namespace support
cat /proc/sys/kernel/unprivileged_userns_clone
# Must output: 1
# If it outputs 0, enable it:
# echo 1 | sudo tee /proc/sys/kernel/unprivileged_userns_clone

# nftables available on host (for inspection labs)
nft --version

# Subuid/subgid mapping (required for rootless)
grep $(whoami) /etc/subuid
grep $(whoami) /etc/subgid
# If missing: sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 $(whoami)
```

### Install missing tools

```bash
# On RHEL 10 / CentOS Stream 10
sudo dnf install -y podman nftables nmap-ncat iputils bind-utils

# On Fedora
sudo dnf install -y podman nftables nmap-ncat iputils bind-utils
```

---

↑ [Back to TOC](#table-of-contents)

## 3. How the Lab Works

Each "node" in the lab is a systemd-enabled UBI 10 container running as your
regular (non-root) user via rootless Podman. Inside each container:

- `systemd` is PID 1 (full init, just like a real system)
- `firewalld` is installed and managed by systemd
- `nftables` tools are installed for inspection
- Network interfaces correspond to Podman virtual networks

```
Your Host (RHEL 10)
│
├── podman network: labnet-external  (172.20.1.0/24)  — simulates "internet"
├── podman network: labnet-dmz       (172.20.2.0/24)  — DMZ segment
└── podman network: labnet-internal  (172.20.3.0/24)  — internal LAN

     ┌─────────────────────────────────────────────────────────────┐
     │  node1 (gateway)                                            │
     │  eth0: 172.20.1.10  ← labnet-external                      │
     │  eth1: 172.20.2.10  ← labnet-dmz                           │
     │  eth2: 172.20.3.10  ← labnet-internal                      │
     └─────────────────────────────────────────────────────────────┘

     ┌──────────────────────────────────┐
     │  node2 (server / DMZ host)       │
     │  eth0: 172.20.2.20 ← labnet-dmz  │
     └──────────────────────────────────┘

     ┌──────────────────────────────────────┐
     │  node3 (client / internal host)      │
     │  eth0: 172.20.3.30 ← labnet-internal │
     └──────────────────────────────────────┘
```

Not every module uses all three nodes. Each module states which nodes are needed
and how to start them.

---

↑ [Back to TOC](#table-of-contents)

## 4. Building the Lab Container Image

We build a single reusable image called `firewalld-lab` based on UBI 10 with
systemd, firewalld, and all lab tools installed.

### 4.1 Create the Containerfile

```bash
mkdir -p ~/firewalld-lab
cat > ~/firewalld-lab/Containerfile << 'EOF'
FROM registry.access.redhat.com/ubi10/ubi:latest

# Install systemd, firewalld, nftables, and useful network tools
RUN dnf install -y \
        systemd \
        firewalld \
        nftables \
        nmap-ncat \
        iputils \
        iproute \
        bind-utils \
        curl \
        wget \
        python3 \
        procps-ng \
        less \
        vim-minimal \
    && dnf clean all \
    && rm -rf /var/cache/dnf

# Enable firewalld at boot
RUN systemctl enable firewalld

# Disable services that conflict with container operation
RUN systemctl disable systemd-resolved 2>/dev/null || true \
 && systemctl disable NetworkManager   2>/dev/null || true \
 && systemctl mask systemd-remount-fs.service \
                dev-hugepages.mount \
                sys-fs-fuse-connections.mount \
                systemd-logind.service \
                getty.target \
                console-getty.service \
    2>/dev/null || true

# Keep the journal small
RUN mkdir -p /etc/systemd/journald.conf.d \
 && printf '[Journal]\nStorage=volatile\nRuntimeMaxUse=20M\n' \
    > /etc/systemd/journald.conf.d/lab.conf

# Expose a simple HTTP port for web server labs
EXPOSE 80 443 8080

STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
EOF
```

### 4.2 Build the image

```bash
podman build -t firewalld-lab ~/firewalld-lab/
```

This takes 2–4 minutes on first build (downloading UBI 10 and packages).
Subsequent builds are cached.

```bash
# Verify the image exists
podman images firewalld-lab
```

Expected output:
```
REPOSITORY                TAG         IMAGE ID      CREATED        SIZE
localhost/firewalld-lab   latest      a1b2c3d4e5f6  2 minutes ago  420 MB
```

> **📝 NOTE — UBI 10 vs RHEL 10**
> UBI (Universal Base Image) 10 is a freely redistributable subset of RHEL 10.
> It uses the same RPM packages and behaves identically for our purposes.
> Full RHEL 10 subscriptions are only needed for subscription-only packages.

---

↑ [Back to TOC](#table-of-contents)

## 5. Podman Networks — Lab Topology

Create three isolated networks to simulate the external, DMZ, and internal
network segments:

```bash
# External / "internet-facing" network
podman network create \
  --subnet 172.20.1.0/24 \
  --gateway 172.20.1.1 \
  labnet-external

# DMZ network
podman network create \
  --subnet 172.20.2.0/24 \
  --gateway 172.20.2.1 \
  labnet-dmz

# Internal LAN network
podman network create \
  --subnet 172.20.3.0/24 \
  --gateway 172.20.3.1 \
  labnet-internal
```

Verify networks were created:

```bash
podman network ls
```

Expected output:
```
NETWORK ID    NAME              DRIVER
2211130d5022  labnet-dmz        bridge
afd6d261fd7e  labnet-external   bridge
3c42e7f2109a  labnet-internal   bridge
podman        podman            bridge
```

> **📝 NOTE — Podman's default network**
> The `podman` network (172.16.0.0/24 by default) is the default for containers
> with no explicit network specified. Our lab containers always specify networks
> explicitly.

---

↑ [Back to TOC](#table-of-contents)

## 6. Starting Lab Nodes

### 6.1 Single-node (most modules)

```bash
podman run -d \
  --name node1 \
  --hostname node1 \
  --network labnet-external:ip=172.20.1.10 \
  --cap-add NET_ADMIN \
  --cap-add SYS_ADMIN \
  --cap-add NET_RAW \
  --security-opt label=disable \
  --tmpfs /tmp \
  --tmpfs /run \
  --tmpfs /run/lock \
  -v /sys/fs/cgroup:/sys/fs/cgroup:ro \
  firewalld-lab
```

### 6.2 Two-node topology (modules 03, 04, 06, 07)

```bash
# Node 1 — connected to external and DMZ
podman run -d \
  --name node1 \
  --hostname node1 \
  --network labnet-external:ip=172.20.1.10 \
  --cap-add NET_ADMIN \
  --cap-add SYS_ADMIN \
  --cap-add NET_RAW \
  --security-opt label=disable \
  --tmpfs /tmp --tmpfs /run --tmpfs /run/lock \
  -v /sys/fs/cgroup:/sys/fs/cgroup:ro \
  firewalld-lab

# Connect node1 to DMZ network after start
podman network connect --ip 172.20.2.10 labnet-dmz node1

# Node 2 — DMZ server
podman run -d \
  --name node2 \
  --hostname node2 \
  --network labnet-dmz:ip=172.20.2.20 \
  --cap-add NET_ADMIN \
  --cap-add SYS_ADMIN \
  --cap-add NET_RAW \
  --security-opt label=disable \
  --tmpfs /tmp --tmpfs /run --tmpfs /run/lock \
  -v /sys/fs/cgroup:/sys/fs/cgroup:ro \
  firewalld-lab
```

### 6.3 Three-node topology (module 05, 13)

```bash
# node1: gateway with all three interfaces
podman run -d \
  --name node1 \
  --hostname node1 \
  --network labnet-external:ip=172.20.1.10 \
  --cap-add NET_ADMIN \
  --cap-add SYS_ADMIN \
  --cap-add NET_RAW \
  --security-opt label=disable \
  --tmpfs /tmp --tmpfs /run --tmpfs /run/lock \
  -v /sys/fs/cgroup:/sys/fs/cgroup:ro \
  firewalld-lab

podman network connect --ip 172.20.2.10 labnet-dmz      node1
podman network connect --ip 172.20.3.10 labnet-internal  node1

# node2: DMZ server
podman run -d \
  --name node2 \
  --hostname node2 \
  --network labnet-dmz:ip=172.20.2.20 \
  --cap-add NET_ADMIN \
  --cap-add SYS_ADMIN \
  --cap-add NET_RAW \
  --security-opt label=disable \
  --tmpfs /tmp --tmpfs /run --tmpfs /run/lock \
  -v /sys/fs/cgroup:/sys/fs/cgroup:ro \
  firewalld-lab

# node3: internal client
podman run -d \
  --name node3 \
  --hostname node3 \
  --network labnet-internal:ip=172.20.3.30 \
  --cap-add NET_ADMIN \
  --cap-add SYS_ADMIN \
  --cap-add NET_RAW \
  --security-opt label=disable \
  --tmpfs /tmp --tmpfs /run --tmpfs /run/lock \
  -v /sys/fs/cgroup:/sys/fs/cgroup:ro \
  firewalld-lab
```

### 6.4 Accessing a node

```bash
# Open a shell inside node1
podman exec -it node1 bash

# Or run a single command
podman exec node1 firewall-cmd --state
```

---

↑ [Back to TOC](#table-of-contents)

## 7. Helper Scripts

To avoid typing long `podman run` commands repeatedly, save these helper scripts
in `~/firewalld-lab/`.

### `start-lab.sh` — start all three nodes

```bash
cat > ~/firewalld-lab/start-lab.sh << 'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail

# Create networks if they don't exist
for net in labnet-external labnet-dmz labnet-internal; do
  podman network exists "$net" || true
done

podman network exists labnet-external 2>/dev/null || \
  podman network create --subnet 172.20.1.0/24 --gateway 172.20.1.1 labnet-external

podman network exists labnet-dmz 2>/dev/null || \
  podman network create --subnet 172.20.2.0/24 --gateway 172.20.2.1 labnet-dmz

podman network exists labnet-internal 2>/dev/null || \
  podman network create --subnet 172.20.3.0/24 --gateway 172.20.3.1 labnet-internal

# Start nodes (skip if already running)
start_node() {
  local name=$1; shift
  if podman container exists "$name"; then
    echo "Container $name already exists — skipping"
    podman start "$name" 2>/dev/null || true
    return
  fi
  podman run -d \
    --name "$name" \
    --hostname "$name" \
    --cap-add NET_ADMIN \
    --cap-add SYS_ADMIN \
    --cap-add NET_RAW \
    --security-opt label=disable \
    --tmpfs /tmp --tmpfs /run --tmpfs /run/lock \
    -v /sys/fs/cgroup:/sys/fs/cgroup:ro \
    "$@" \
    firewalld-lab
  echo "Started: $name"
}

start_node node1 --network labnet-external:ip=172.20.1.10
podman network connect --ip 172.20.2.10 labnet-dmz     node1 2>/dev/null || true
podman network connect --ip 172.20.3.10 labnet-internal node1 2>/dev/null || true

start_node node2 --network labnet-dmz:ip=172.20.2.20
start_node node3 --network labnet-internal:ip=172.20.3.30

# Wait for systemd / firewalld to initialise
echo "Waiting for firewalld to start on all nodes..."
for node in node1 node2 node3; do
  for i in $(seq 1 15); do
    if podman exec "$node" firewall-cmd --state 2>/dev/null | grep -q running; then
      echo "  $node: firewalld running"
      break
    fi
    sleep 1
  done
done

echo ""
echo "Lab ready. Access nodes with:"
echo "  podman exec -it node1 bash"
echo "  podman exec -it node2 bash"
echo "  podman exec -it node3 bash"
SCRIPT
chmod +x ~/firewalld-lab/start-lab.sh
```

### `stop-lab.sh` — stop all nodes (preserves state)

```bash
cat > ~/firewalld-lab/stop-lab.sh << 'SCRIPT'
#!/usr/bin/env bash
for node in node1 node2 node3; do
  podman stop "$node" 2>/dev/null && echo "Stopped: $node" || true
done
SCRIPT
chmod +x ~/firewalld-lab/stop-lab.sh
```

### `reset-lab.sh` — destroy and recreate all nodes from scratch

```bash
cat > ~/firewalld-lab/reset-lab.sh << 'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
echo "WARNING: This will destroy all lab containers and remove firewall config."
read -rp "Continue? [y/N] " confirm
[[ "$confirm" == [yY] ]] || exit 1

for node in node1 node2 node3; do
  podman rm -f "$node" 2>/dev/null && echo "Removed: $node" || true
done

~/firewalld-lab/start-lab.sh
SCRIPT
chmod +x ~/firewalld-lab/reset-lab.sh
```

---

↑ [Back to TOC](#table-of-contents)

## 8. Verifying firewalld Inside a Node

Once a node is running, verify that firewalld started correctly:

```bash
podman exec node1 systemctl status firewalld
```

Expected output (truncated):
```
● firewalld.service - firewalld - dynamic firewall daemon
     Loaded: loaded (/usr/lib/systemd/system/firewalld.service; enabled)
     Active: active (running) since ...
       Docs: man:firewalld(1)
   Main PID: 42 (firewalld)
```

```bash
# Check firewalld state via firewall-cmd
podman exec node1 firewall-cmd --state
# running

# List default zone
podman exec node1 firewall-cmd --get-default-zone
# public

# List active zones and bound interfaces
podman exec node1 firewall-cmd --get-active-zones
# public
#   interfaces: eth0

# Show full config of the default zone
podman exec node1 firewall-cmd --list-all
```

Expected `--list-all` output (fresh container):
```
public (active)
  target: default
  icmp-block-inversion: no
  interfaces: eth0
  sources:
  services: cockpit dhcpv6-client ssh
  ports:
  protocols:
  forward: yes
  masquerade: no
  forward-ports:
  source-ports:
  icmp-blocks:
  rich rules:
```

> **📝 NOTE — cockpit and dhcpv6-client in the default zone**
> These services appear in the default `public` zone because the base UBI image
> ships this as a reasonable default for cloud/server use. We will customise
> zones in Module 03. For now they are harmless inside our isolated container.

---

↑ [Back to TOC](#table-of-contents)

## 9. Topology Reference Table

Use this table as a quick reference when each module says "start the two-node
topology":

| Topology | Nodes | Networks | Used In |
|----------|-------|----------|---------|
| **Single** | node1 only | labnet-external | Modules 01, 02, 04, 06, 09, 10, 11, 12 |
| **Two-node** | node1 + node2 | external + dmz | Modules 03, 07 |
| **Three-node** | node1 + node2 + node3 | external + dmz + internal | Modules 05, 08, 13 |

Each module header specifies exactly which topology it uses and includes the
exact start commands if they differ from the defaults above.

---

↑ [Back to TOC](#table-of-contents)

## Lab 0 — Spin Up and Verify

**Topology:** Single-node (node1 only)

**Objective:** Build the image, start node1, verify firewalld is running, and
explore the initial state.

---

### Step 1 — Build the image

```bash
# 🔧 LAB STEP
mkdir -p ~/firewalld-lab
# Create the Containerfile as shown in section 4.1 above, then:
podman build -t firewalld-lab ~/firewalld-lab/
```

Expected: Build completes with `Successfully tagged localhost/firewalld-lab:latest`

---

### Step 2 — Create networks

```bash
# 🔧 LAB STEP
podman network create --subnet 172.20.1.0/24 --gateway 172.20.1.1 labnet-external
podman network create --subnet 172.20.2.0/24 --gateway 172.20.2.1 labnet-dmz
podman network create --subnet 172.20.3.0/24 --gateway 172.20.3.1 labnet-internal
```

---

### Step 3 — Start node1

```bash
# 🔧 LAB STEP
podman run -d \
  --name node1 \
  --hostname node1 \
  --network labnet-external:ip=172.20.1.10 \
  --cap-add NET_ADMIN \
  --cap-add SYS_ADMIN \
  --cap-add NET_RAW \
  --security-opt label=disable \
  --tmpfs /tmp --tmpfs /run --tmpfs /run/lock \
  -v /sys/fs/cgroup:/sys/fs/cgroup:ro \
  firewalld-lab
```

---

### Step 4 — Wait for systemd to initialise

```bash
# 🔧 LAB STEP
# Wait a few seconds, then check
sleep 3
podman exec node1 firewall-cmd --state
```

If you see `running`, proceed. If you see `not running`, wait a few more seconds
and try again — systemd is still booting.

---

### Step 5 — Explore the initial state

Open a shell in node1:

```bash
# 🔧 LAB STEP
podman exec -it node1 bash
```

Now inside the container, run these exploration commands:

```bash
# Where is firewalld's configuration?
ls /etc/firewalld/

# What zones exist?
firewall-cmd --get-zones

# Which zone is active and on which interface?
firewall-cmd --get-active-zones

# What is the full config of the public zone?
firewall-cmd --list-all

# What services are pre-defined?
firewall-cmd --get-services | tr ' ' '\n' | head -20

# Look at a service definition
cat /usr/lib/firewalld/services/ssh.xml

# What does firewalld's config look like in XML?
ls /etc/firewalld/zones/
```

> **💡 CONCEPT CHECK**
> Notice that `/etc/firewalld/zones/` may be empty, yet `firewall-cmd --get-zones`
> shows many zones. Where are the default zone definitions stored?
>
> Answer: `/usr/lib/firewalld/zones/` contains the shipped defaults. Files in
> `/etc/firewalld/zones/` are *overrides* — only customised zones appear there.
> This mirrors how systemd handles unit files.

---

### Step 6 — Inspect the nftables ruleset

```bash
# 🔧 LAB STEP (still inside node1)
nft list ruleset
```

You should see a set of tables, chains, and rules that firewalld has generated.
We will study every line of this output in Module 02. For now, observe that:

1. There is a table called `inet firewalld`
2. There are chains with names like `filter_INPUT`, `filter_FORWARD`
3. There are rules referencing zones by name

> **💡 CONCEPT CHECK**
> Notice that `nft list ruleset` shows rules, but `firewall-cmd --list-all`
> shows services and ports — these are two different views of the same firewall.
> firewalld translates its zone/service config into nftables rules. Module 02
> explains the full translation in detail.

---

### Step 7 — Make a change and observe it

```bash
# 🔧 LAB STEP
# Add HTTP service to the public zone (runtime only)
firewall-cmd --zone=public --add-service=http

# Verify it appeared
firewall-cmd --zone=public --list-services

# Now look at nftables again — what changed?
nft list ruleset | grep -A5 "http"

# Remove it
firewall-cmd --zone=public --remove-service=http

# Verify it's gone
firewall-cmd --zone=public --list-services
```

> **💡 CONCEPT CHECK**
> You added a service without `--permanent`. Exit the container and restart it:
> ```bash
> exit
> podman restart node1
> sleep 3
> podman exec node1 firewall-cmd --zone=public --list-services
> ```
> The `http` service should be gone. This demonstrates the runtime vs permanent
> distinction that Module 01 covers in full depth.

---

### Step 8 — Exit and verify from outside

```bash
# 🔧 LAB STEP (back on your host)
# Check the container is running
podman ps

# Run a firewall-cmd from outside without entering the container
podman exec node1 firewall-cmd --get-default-zone
```

---

↑ [Back to TOC](#table-of-contents)

## Teardown and Reset

### Stop nodes (preserves configuration)

```bash
podman stop node1 node2 node3
```

### Restart stopped nodes

```bash
podman start node1
# Wait for systemd
sleep 3
podman exec node1 firewall-cmd --state
```

### Full reset (destroy all lab containers)

```bash
podman rm -f node1 node2 node3
# Then use start-lab.sh to recreate from scratch
~/firewalld-lab/start-lab.sh
```

### Remove everything including networks and image

```bash
podman rm -f node1 node2 node3
podman network rm labnet-external labnet-dmz labnet-internal
podman rmi firewalld-lab
```

---

↑ [Back to TOC](#table-of-contents)

## Troubleshooting the Lab Setup

### firewalld not starting inside the container

**Symptom:** `firewall-cmd --state` returns `not running` even after waiting.

**Check 1:** systemd boot status
```bash
podman exec node1 systemctl --failed
```

**Check 2:** firewalld journal logs
```bash
podman exec node1 journalctl -u firewalld --no-pager
```

**Common cause:** The container was started without `--cap-add NET_ADMIN` or
`--cap-add SYS_ADMIN`. These capabilities are required for nftables manipulation.

**Fix:** Remove and recreate the container with the correct flags.

---

### nft: Operation not permitted

**Symptom:** `nft list ruleset` inside the container gives a permission error.

**Cause:** Missing `NET_ADMIN` capability or SELinux label not disabled.

**Fix:** Ensure `--cap-add NET_ADMIN` and `--security-opt label=disable` are
present in the `podman run` command.

---

### Cannot reach node2 from node1

**Symptom:** `ping 172.20.2.20` from node1 fails.

**Check:** Verify node1 is connected to labnet-dmz:
```bash
podman inspect node1 --format '{{json .NetworkSettings.Networks}}' | python3 -m json.tool
```

**Fix:**
```bash
podman network connect --ip 172.20.2.10 labnet-dmz node1
```

---

### Image build fails on dnf install

**Symptom:** Package installation fails during `podman build`.

**Cause:** UBI 10 requires Red Hat CDN access for some packages. If you are on
a registered RHEL system, ensure the host's subscription is available.

**Workaround:** For fully offline environments, replace `ubi10/ubi:latest` with
`quay.io/centos/centos:stream10` in the Containerfile — CentOS Stream 10 uses
the same packages without subscription requirements.

---

*Module 00 complete. You now have a working lab environment.*

**Continue to [Module 01 — Introduction and Architecture →](./01-introduction-and-architecture.md)**

---

© 2026 Jaco Steyn — Licensed under CC BY-SA 4.0

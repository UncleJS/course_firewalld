# Module 01 — Introduction and Architecture

> **Goal:** Understand what firewalld is, why it exists, how it fits in the
> Linux networking stack, and the fundamental two-layer model that governs every
> operation you will ever perform. This conceptual foundation is the lens through
> which every subsequent module makes sense.

---

## Table of Contents

1. [What Is a Firewall and Why Does Linux Need One?](#1-what-is-a-firewall-and-why-does-linux-need-one)
2. [A Brief History: From ipchains to nftables](#2-a-brief-history-from-ipchains-to-nftables)
3. [The Linux Packet Filtering Stack](#3-the-linux-packet-filtering-stack)
4. [Enter firewalld: The Dynamic Firewall Manager](#4-enter-firewalld-the-dynamic-firewall-manager)
5. [firewalld's Internal Architecture](#5-firewallds-internal-architecture)
6. [The Two-Layer Model: Runtime vs Permanent](#6-the-two-layer-model-runtime-vs-permanent)
7. [Configuration Files and Their Locations](#7-configuration-files-and-their-locations)
8. [The firewall-cmd Tool](#8-the-firewall-cmd-tool)
9. [firewalld on RHEL 10: What Changed](#9-firewalld-on-rhel-10-what-changed)
10. [Lab 1 — Explore the Daemon and Two-Layer Model](#lab-1--explore-the-daemon-and-two-layer-model)

---

## 1. What Is a Firewall and Why Does Linux Need One?

A firewall is a security boundary that inspects network traffic and decides
whether to allow or deny each packet based on a set of rules. Think of it as a
security guard at the entrance to a building: every visitor (packet) is checked
against a list of criteria before being allowed in, turned away, or escorted
out.

At the most basic level, a packet arrives at a network interface with:
- A **source IP address** — where it came from
- A **destination IP address** — where it is going
- A **protocol** — TCP, UDP, ICMP, etc.
- A **source port** and **destination port** (for TCP/UDP)
- A **state** — is this the start of a new connection, part of an existing one,
  or unrelated?

A firewall evaluates these properties against its rule set and takes an action:
**accept** (let it through), **drop** (silently discard), or **reject** (discard
and send back an error).

### Why does a Linux server need a firewall?

Even a freshly installed Linux server with no services running benefits from a
firewall for several reasons:

1. **Defence in depth:** Services you didn't intentionally start (or didn't
   realise start by default) are not exposed.
2. **Limiting blast radius:** If one service is compromised, the firewall limits
   what an attacker can reach from inside.
3. **Logging and visibility:** A firewall provides a record of what traffic was
   seen and denied, which is invaluable for incident response.
4. **Compliance:** Regulatory frameworks (PCI-DSS, HIPAA, ISO 27001) require
   host-based firewalls.
5. **Network segmentation:** A Linux host acting as a router or gateway enforces
   which traffic flows between network segments.

---

## 2. A Brief History: From ipchains to nftables

Understanding where firewalld came from helps explain its design choices.

### The ipchains era (kernel 2.2)

Linux's first widely-used packet filter was `ipchains`. Rules were loaded as a
flat list of chains. It worked but lacked stateful connection tracking — it
couldn't distinguish between a new connection and a reply to an existing one.

### iptables (kernel 2.4, circa 2001)

`iptables` introduced **stateful packet inspection** via the `conntrack` kernel
module. A packet could be classified as `NEW`, `ESTABLISHED`, `RELATED`, or
`INVALID` — a huge improvement for writing firewall rules, since you could now
say "allow all traffic that is part of an already-established connection."

`iptables` became the standard Linux firewall tool for 20+ years. It is a
userspace tool that interacts with the `netfilter` kernel framework to install
rules. It works, but has significant limitations:

- **Separate tools** for IPv4 (`iptables`), IPv6 (`ip6tables`), bridge
  (`ebtables`) — same concepts, three different tools and syntaxes
- **No atomic updates** — loading a new ruleset is not transactional; there is
  a brief window during update where rules are inconsistent
- **No sets** — matching against a list of 10,000 IP addresses required 10,000
  individual rules, which is slow
- **Static rules** — any dynamic change (like adding a port while a service
  starts) required reloading the entire ruleset

### firewalld (2011, RHEL 7+)

`firewalld` was introduced to solve the management problem: instead of a flat
list of static rules, it provides a **dynamic, zone-based firewall** daemon.
Key innovations:

- Rules are managed at runtime without losing existing connections
- The zone abstraction makes intent clear (this is the "trusted internal" zone)
- D-Bus interface allows other services (NetworkManager, libvirt, Podman) to
  register themselves with the firewall
- Permanent and runtime configs are kept separate

Initially firewalld used iptables as its backend. From RHEL 8 onward it gained
an nftables backend. In RHEL 10, nftables is the only backend.

### nftables (kernel 3.13+, production RHEL 8+)

`nftables` is the modern replacement for the entire iptables/ip6tables/ebtables
family. It addresses all of iptables' limitations:

- **Single tool** for IPv4, IPv6, bridge, ARP, and more
- **Atomic rule updates** — rulesets are loaded as a transaction
- **Native sets** — match millions of addresses in a single rule
- **Expressions** — powerful matching capabilities built into the rule language
- **Better performance** — especially for large rulesets

On RHEL 10, the kernel netfilter framework is still the underlying engine.
`nftables` is the userspace interface. `firewalld` is the management layer on
top of `nftables`. You will work primarily with `firewall-cmd`, but understanding
`nftables` deeply is what separates expert practitioners from competent users.

```
┌─────────────────────────────────────────┐
│           Your Intent                   │
│     "Allow HTTP from the internet"      │
└─────────────────────┬───────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────┐
│         firewall-cmd (CLI)              │
│    Human-friendly command interface     │
└─────────────────────┬───────────────────┘
                      │  D-Bus
                      ▼
┌─────────────────────────────────────────┐
│         firewalld (daemon)              │
│    Zone/policy/service management       │
│    Translates config → nftables rules   │
└─────────────────────┬───────────────────┘
                      │  nft API
                      ▼
┌─────────────────────────────────────────┐
│         nftables (userspace)            │
│    Rule language and kernel interface   │
└─────────────────────┬───────────────────┘
                      │  netlink socket
                      ▼
┌─────────────────────────────────────────┐
│    Linux Kernel — netfilter subsystem   │
│    Actual packet inspection engine      │
│    conntrack, NAT, verdict tables       │
└─────────────────────┬───────────────────┘
                      │
                      ▼
              Network Packets
```

---

## 3. The Linux Packet Filtering Stack

Before firewalld can make sense, you need to understand where in the kernel
packets are inspected.

### Netfilter hooks

The Linux kernel has five **netfilter hooks** — specific points in the packet
processing path where kernel modules can register to inspect, modify, or drop
packets:

```
                 ┌─────────────┐
                 │   PREROUTING│ ← Packets arrive here first (all incoming)
                 └──────┬──────┘
                        │
           ┌────────────┴──────────────┐
           │                           │
    ┌──────▼──────┐             ┌──────▼──────┐
    │   INPUT     │             │   FORWARD   │
    │(for host)   │             │(for routing)│
    └──────┬──────┘             └──────┬──────┘
           │                           │
    ┌──────▼──────┐             ┌──────▼──────┐
    │   Local     │             │ POSTROUTING │ ← Outgoing routed packets
    │  Process    │             └─────────────┘
    └──────┬──────┘
           │
    ┌──────▼──────┐
    │   OUTPUT    │ ← Packets generated by local processes
    └──────┬──────┘
           │
    ┌──────▼──────┐
    │ POSTROUTING │ ← All outgoing packets
    └─────────────┘
```

**INPUT** — traffic destined for the local machine (e.g., an SSH connection to
this server)

**FORWARD** — traffic passing through the machine from one interface to another
(e.g., a router forwarding packets between networks)

**OUTPUT** — traffic generated by processes running on this machine

**PREROUTING** — before routing decisions are made; used for DNAT (destination
NAT / port forwarding)

**POSTROUTING** — after routing decisions; used for SNAT / masquerading

### Connection tracking (conntrack)

The `conntrack` kernel module maintains a table of all active network
connections. When a packet arrives, conntrack classifies it:

| State | Meaning |
|-------|---------|
| `NEW` | First packet of a new connection |
| `ESTABLISHED` | Part of an already-seen connection |
| `RELATED` | Associated with an existing connection (e.g., FTP data channel) |
| `INVALID` | Doesn't match any known connection; usually dropped |
| `UNTRACKED` | Explicitly excluded from tracking |

This is crucial for firewall rules. A typical rule set says:
- Drop INVALID packets
- Accept ESTABLISHED and RELATED packets (replies to connections we initiated)
- Apply zone rules only to NEW packets

This means you only need rules for *initiating* connections — all replies are
automatically permitted.

---

## 4. Enter firewalld: The Dynamic Firewall Manager

`firewalld` is a userspace daemon that manages the Linux firewall. It was
designed to solve specific operational problems:

### Problem 1: Static vs Dynamic

Traditional iptables scripts loaded rules once at boot and that was it. Adding
a rule meant reloading the entire script. Services that needed firewall access
(like a web server or VPN) had to be manually accounted for.

firewalld is **dynamic** — you can add and remove rules at runtime without
disconnecting existing connections. When NetworkManager brings up a new
interface, it can tell firewalld which zone to put it in. When Podman starts a
container, it can register port forwarding rules. All without touching existing
connections.

### Problem 2: Intent vs Implementation

iptables rules are implementation-level: "accept TCP port 443." firewalld rules
express intent: "allow the https service in the public zone." This is more
readable and less error-prone.

### Problem 3: Zone-based organisation

Rather than one flat list of rules, firewalld organises rules into **zones**.
Each zone represents a trust level. Interfaces are assigned to zones. Rules
are applied per-zone.

This mirrors how you think about networks: "this interface faces the internet,
so it's in the public zone with restrictive rules; that interface faces our
internal LAN, so it's in the internal zone with permissive rules."

---

## 5. firewalld's Internal Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                        firewalld daemon                            │
│                                                                    │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────────┐   │
│  │  D-Bus       │   │  XML Config  │   │  Backend (nftables)  │   │
│  │  Interface   │   │  Parser      │   │  Translator          │   │
│  └──────┬───────┘   └──────┬───────┘   └──────────┬───────────┘   │
│         │                  │                        │               │
│  ┌──────▼───────────────────▼────────────────────── │──────────┐   │
│  │              Zone / Policy Engine                │          │   │
│  │   Zones, Policies, Services, Rich Rules,         │          │   │
│  │   IP Sets, Port Forwarding, Masquerade           │          │   │
│  └──────────────────────────────────────────────────┘          │   │
│                                                                 │   │
│  ┌──────────────────────────────────────────────────────────┐  │   │
│  │              Runtime State (in-memory)                   │  │   │
│  └──────────────────────────────────────────────────────────┘  │   │
│                                                                 │   │
│  ┌──────────────────────────────────────────────────────────┐  │   │
│  │              Permanent State (/etc/firewalld/)           │  │   │
│  └──────────────────────────────────────────────────────────┘  │   │
└────────────────────────────────────────────────────────────────────┘
```

### D-Bus Interface

firewalld exposes its interface via **D-Bus**, the Linux inter-process
communication system. This is how:

- `firewall-cmd` sends commands to the daemon
- NetworkManager tells firewalld which zone an interface belongs to
- Podman registers port forwarding rules when containers start
- `libvirt` registers network bridges for virtual machines

You can interact with firewalld directly via D-Bus using `dbus-send` or
`gdbus`, though this is rarely needed in practice.

### Zone and Policy Engine

The core of firewalld. Maintains the authoritative state of all zones, policies,
services, and rules. When a change is made, this engine determines the correct
nftables rules to add or remove.

### Backend (nftables Translator)

Takes the zone/policy configuration and translates it to nftables rules. On
RHEL 10 this is always the nftables backend. The translator ensures that:

1. Rules are generated in the correct order (chain priorities)
2. Zone-to-interface/source mappings are correct
3. Rich rules appear at the right priority within their zone
4. Policy rules appear before or after zone rules as specified

---

## 6. The Two-Layer Model: Runtime vs Permanent

This is the single most important concept in firewalld. Misunderstanding it is
the source of most beginner confusion and operational errors.

firewalld maintains **two separate states simultaneously**:

```
┌─────────────────────────────────────────────────────────────────────┐
│                         RUNTIME STATE                               │
│                      (in kernel/memory)                             │
│                                                                     │
│   • What is ACTUALLY enforced right now                             │
│   • What nftables rules are ACTUALLY loaded                         │
│   • Changes take effect IMMEDIATELY                                 │
│   • Changes are LOST on firewall reload or system reboot            │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                        PERMANENT STATE                              │
│                   (/etc/firewalld/ on disk)                         │
│                                                                     │
│   • What will be enforced AFTER the next reload                     │
│   • XML files on disk                                               │
│   • Changes do NOT take effect immediately                          │
│   • Changes SURVIVE reload and reboot                               │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### The three operations

| Operation | Flag | What it does |
|-----------|------|--------------|
| **Runtime change** | *(no flag)* | Modifies runtime only; immediate effect; lost on reload |
| **Permanent change** | `--permanent` | Modifies disk config only; no immediate effect; survives reload |
| **Runtime + Permanent** | Run command twice, or `--runtime-to-permanent` | Both layers updated |

### Common workflow 1: Test then make permanent

This is the safest approach when you're not sure a rule is correct:

```bash
# Step 1: Add to runtime only (instant, reversible)
firewall-cmd --zone=public --add-service=http
# Test that your application works

# Step 2: If it works, save runtime config to permanent
firewall-cmd --runtime-to-permanent

# Step 3: Reload to verify permanent config loads cleanly
firewall-cmd --reload
```

### Common workflow 2: Permanent with manual reload

Some operators prefer explicit control:

```bash
# Add to permanent config (no immediate effect)
firewall-cmd --permanent --zone=public --add-service=http

# Activate permanent config by reloading
firewall-cmd --reload
```

### Common workflow 3: Both at once (risky)

```bash
# Add to both runtime AND permanent simultaneously
firewall-cmd --permanent --zone=public --add-service=http
firewall-cmd --zone=public --add-service=http
```

Running the command twice — once with `--permanent` and once without — achieves
both. This is common in scripts but can lead to inconsistency if one command
fails.

> **⚠️  IMPORTANT — The most common beginner mistake**
> Adding a rule with `--permanent` and wondering why it doesn't work immediately.
> Always remember: `--permanent` writes to disk but does NOT activate the rule.
> You need `firewall-cmd --reload` to load permanent config into runtime.

### What does `--reload` do?

`firewall-cmd --reload` replaces the **entire runtime state** with the permanent
config. It is a "soft reload" — it does NOT drop existing TCP connections. The
nftables ruleset is swapped atomically.

```bash
# Soft reload (maintains existing connections)
firewall-cmd --reload

# Hard reload (breaks existing connections — rarely needed)
firewall-cmd --complete-reload
```

Use `--complete-reload` only when you need to flush connection tracking state,
for example after a major zone restructuring.

### Checking which layer you're looking at

```bash
# Show RUNTIME config
firewall-cmd --list-all --zone=public

# Show PERMANENT config (what will survive reload)
firewall-cmd --permanent --list-all --zone=public
```

If these outputs differ, you have a discrepancy between runtime and permanent
state — something was added at runtime but not made permanent, or vice versa.

---

## 7. Configuration Files and Their Locations

### System defaults (read-only)

```
/usr/lib/firewalld/
├── zones/          ← Predefined zone XML (public, internal, dmz, etc.)
├── services/       ← Predefined service XML (http, ssh, dns, etc.)
├── icmptypes/      ← ICMP type definitions
├── ipsets/         ← Predefined IP sets (rare)
└── policies/       ← Predefined policies
```

**Never edit files here.** They are owned by the `firewalld` package and will
be overwritten on upgrade.

### User customisations (read/write)

```
/etc/firewalld/
├── firewalld.conf         ← Main daemon configuration
├── zones/                 ← Custom/overridden zone XML
├── policies/              ← Custom policy XML
├── services/              ← Custom service XML
├── ipsets/                ← Custom IP set XML
├── helpers/               ← Custom connection tracking helpers
└── direct.xml             ← Direct (raw) rules (Module 12)
```

Files here **override** the system defaults. If `/etc/firewalld/zones/public.xml`
exists, it replaces `/usr/lib/firewalld/zones/public.xml`. If it doesn't exist,
the system default is used.

### `firewalld.conf` — key options

```ini
# /etc/firewalld/firewalld.conf

# Logging for denied packets (off/all/unicast/broadcast/multicast)
LogDenied=off

# Lock down firewall to whitelist only
Lockdown=no

# Flush all rules on reload (vs incremental)
FlushAllOnReload=yes

# Use nftables or iptables backend (RHEL 10: always nftables)
FirewallBackend=nftables

# Whether container-published ports bypass firewalld
StrictForwardPorts=no

# Default zone for unconfigured interfaces
DefaultZone=public
```

---

## 8. The firewall-cmd Tool

`firewall-cmd` is the primary command-line interface for firewalld. It
communicates with the daemon over D-Bus and can query or modify both runtime
and permanent state.

### Command structure

```
firewall-cmd [OPTIONS] [--permanent] --COMMAND [ARGUMENTS]
```

- `--permanent` modifies persistent config (disk) — without it, modifies runtime
- Many commands have `--add-*`, `--remove-*`, `--list-*`, and `--get-*` variants

### Essential status commands

```bash
# Is firewalld running?
firewall-cmd --state

# What version of firewalld?
firewall-cmd --version

# Detailed status (as systemctl shows)
systemctl status firewalld

# Reload permanent config into runtime
firewall-cmd --reload

# Save current runtime config to permanent
firewall-cmd --runtime-to-permanent
```

### Getting information

```bash
# List all zones and their full config
firewall-cmd --list-all-zones

# Show active zones (zones with bound interfaces or sources)
firewall-cmd --get-active-zones

# Show the default zone
firewall-cmd --get-default-zone

# Show all available services
firewall-cmd --get-services

# Show details of a specific service
firewall-cmd --info-service=http

# Show details of a specific zone
firewall-cmd --info-zone=public
```

### How firewall-cmd handles errors

```bash
# Success always outputs:
success

# Failure outputs the error and exits non-zero:
Error: ALREADY_ENABLED: 'http' already in 'public'
```

In scripts, always check the exit code:

```bash
if firewall-cmd --zone=public --add-service=http; then
  echo "Added successfully"
else
  echo "Failed to add service"
fi
```

---

## 9. firewalld on RHEL 10: What Changed

RHEL 10 ships firewalld version 2.x with several important changes:

### nftables-only backend

The iptables backend is gone. RHEL 10 uses nftables exclusively. This means:

- The `iptables`, `ip6tables`, and `ebtables` commands are deprecated and may
  not be installed
- Direct rules use nftables syntax where applicable
- The nftables ruleset is richer and more structured than the old iptables output

### Policy Sets (firewalld 2.4+)

Policy Sets are named, pre-packaged collections of policies for common use
cases. The most useful is the **gateway** policy set, which turns a host into
a NAT router with one command:

```bash
# Activate the gateway policy set
firewall-cmd --policy-set gateway --remove-disable

# See what it created
firewall-cmd --list-all-policies
```

### StrictForwardPorts

Controls whether container runtimes (Podman, Docker) can implicitly allow their
published ports through the firewall:

```ini
# /etc/firewalld/firewalld.conf
StrictForwardPorts=no   # Default: container-published ports are allowed (seamless)
StrictForwardPorts=yes  # Strict: only explicit firewalld rules work
```

This is covered in full detail in Module 08.

### Improved container zone integration

firewalld 2.x has better integration with Podman's Netavark networking stack,
allowing container networks to be automatically bound to firewalld zones.

### `firewall-config` GUI removed

The `firewall-config` graphical tool was removed from RHEL 10. All configuration
is done via `firewall-cmd` or by editing XML files directly.

---

## Lab 1 — Explore the Daemon and Two-Layer Model

**Topology:** Single-node (node1 only)

**Objective:** Observe the two-layer model in action — make runtime changes,
verify they disappear on reload, make permanent changes, verify they survive.

---

### Step 1 — Start node1 and open a shell

```bash
# 🔧 LAB STEP (on host)
podman start node1 2>/dev/null || podman run -d \
  --name node1 --hostname node1 \
  --network labnet-external:ip=172.20.1.10 \
  --cap-add NET_ADMIN --cap-add SYS_ADMIN --cap-add NET_RAW \
  --security-opt label=disable \
  --tmpfs /tmp --tmpfs /run --tmpfs /run/lock \
  -v /sys/fs/cgroup:/sys/fs/cgroup:ro \
  firewalld-lab

sleep 3
podman exec -it node1 bash
```

---

### Step 2 — Inspect the daemon

```bash
# 🔧 LAB STEP (inside node1)

# Check status
firewall-cmd --state

# Version
firewall-cmd --version

# Check the systemd service
systemctl status firewalld --no-pager

# Where is the config?
ls /etc/firewalld/
ls /usr/lib/firewalld/
```

---

### Step 3 — Observe the two-layer model

```bash
# 🔧 LAB STEP

# Check runtime config (no --permanent)
firewall-cmd --list-all --zone=public

# Check permanent config (with --permanent)
firewall-cmd --permanent --list-all --zone=public
```

> **💡 CONCEPT CHECK**
> Both outputs should be identical right now — we haven't made any changes yet.
> The runtime was initialised from the permanent config when firewalld started.

---

### Step 4 — Make a runtime-only change

```bash
# 🔧 LAB STEP

# Add HTTPS to the public zone — runtime only
firewall-cmd --zone=public --add-service=https

# Verify it's in the RUNTIME config
firewall-cmd --list-all --zone=public
# Look for 'https' in services line

# Is it in the PERMANENT config?
firewall-cmd --permanent --list-all --zone=public
# https should NOT appear here
```

---

### Step 5 — Reload and observe the change disappear

```bash
# 🔧 LAB STEP

# Reload: runtime is replaced with permanent
firewall-cmd --reload

# Check runtime config again
firewall-cmd --list-all --zone=public
# https is gone — it was never permanent
```

> **💡 CONCEPT CHECK**
> This is the key lesson: `--reload` wipes runtime state and replaces it with
> what's on disk. Anything you added without `--permanent` is gone.

---

### Step 6 — Make a permanent change

```bash
# 🔧 LAB STEP

# Add HTTPS permanently
firewall-cmd --permanent --zone=public --add-service=https

# Is it in runtime yet?
firewall-cmd --list-all --zone=public
# NO — permanent changes need a reload to activate

# Is it in permanent config?
firewall-cmd --permanent --list-all --zone=public
# YES — it's on disk

# Now look at the XML file
cat /etc/firewalld/zones/public.xml
```

---

### Step 7 — Reload to activate the permanent change

```bash
# 🔧 LAB STEP

firewall-cmd --reload

# Now check runtime
firewall-cmd --list-all --zone=public
# https is now in runtime — it was loaded from permanent
```

---

### Step 8 — Use runtime-to-permanent

```bash
# 🔧 LAB STEP

# Add a service at runtime only
firewall-cmd --zone=public --add-service=ftp

# Verify runtime has it, permanent doesn't
firewall-cmd --list-all --zone=public
firewall-cmd --permanent --list-all --zone=public

# Save runtime state to permanent
firewall-cmd --runtime-to-permanent

# Now both should match
firewall-cmd --list-all --zone=public
firewall-cmd --permanent --list-all --zone=public
```

---

### Step 9 — Inspect the kernel-level rules

```bash
# 🔧 LAB STEP

# See what firewalld actually loaded into nftables
nft list ruleset

# Count the rules
nft list ruleset | grep -c "^  \+[a-z]"
```

> **💡 CONCEPT CHECK**
> Compare the `nft list ruleset` output to `firewall-cmd --list-all`. Can you
> find the nftables rule that corresponds to the `https` service you added?
> Look for `tcp dport 443`. Module 02 will explain every line of this output.

---

### Step 10 — Clean up

```bash
# 🔧 LAB STEP

# Remove the services we added
firewall-cmd --permanent --zone=public --remove-service=https
firewall-cmd --permanent --zone=public --remove-service=ftp
firewall-cmd --reload

# Verify we're back to the original state
firewall-cmd --list-all --zone=public
```

---

### Summary

In this lab you observed:

| Action | Runtime effect | Permanent effect |
|--------|----------------|-----------------|
| Add service (no flag) | Immediate ✓ | None ✗ |
| Reload | Runtime replaced from disk | No change |
| Add service (`--permanent`) | None (until reload) | Written to disk ✓ |
| Reload after `--permanent` | Activated ✓ | No change |
| `--runtime-to-permanent` | No change | Runtime state saved ✓ |

This table is worth memorising. Every firewall operation you perform for the
rest of this course uses this model.

---

*Module 01 complete.*

**Continue to [Module 02 — nftables Fundamentals →](./02-nftables-fundamentals.md)**

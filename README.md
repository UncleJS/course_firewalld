# Firewalld: Zero to Expert on RHEL 10

A comprehensive, hands-on course covering firewalld from first principles to
expert-level mastery — on Red Hat Enterprise Linux 10, with rootless Podman
container labs throughout.

---

## Who This Course Is For

| Level | You are ready if… |
|-------|-------------------|
| **Beginner** | You know what a firewall *is* conceptually but have never configured one on Linux |
| **Intermediate** | You have used `firewall-cmd` before but lack a clear mental model of zones, policies, and nftables |
| **Advanced** | You want to master policies, rich rules, IP sets, container integration, and performance tuning |

No prior firewalld or iptables knowledge is assumed. Familiarity with Linux
command-line basics (files, processes, systemd) and basic networking concepts
(IP addresses, ports, TCP/UDP) is expected.

---

## What You Will Learn

By the end of this course you will be able to:

- Explain how firewalld, nftables, and the Linux kernel netfilter subsystem
  relate to one another
- Design and implement a zone-based firewall policy for any network topology
- Write rich rules for complex, fine-grained traffic control
- Configure NAT, masquerading, and port forwarding
- Integrate firewalld with rootless Podman containers on RHEL 10
- Use IP sets for efficient dynamic allow/block lists
- Harden a system with lockdown mode and SELinux integration
- Inspect the raw nftables ruleset that firewalld generates and use it for
  troubleshooting
- Diagnose and resolve real-world firewall problems systematically

---

## Course Structure

```
course_firewalld/
├── README.md                              ← You are here
├── 00-setup-lab-environment.md           ← Start here: build your lab
├── 01-introduction-and-architecture.md
├── 02-nftables-fundamentals.md
├── 03-zones-and-trust-model.md
├── 04-services-ports-and-protocols.md
├── 05-policies-and-inter-zone-routing.md
├── 06-rich-rules.md
├── 07-nat-masquerading-and-port-forwarding.md
├── 08-container-integration.md
├── 09-ipsets-and-dynamic-filtering.md
├── 10-logging-troubleshooting-and-debugging.md
├── 11-lockdown-mode-and-hardening.md
├── 12-direct-rules-and-advanced-nftables.md
├── 13-capstone-project.md
├── cheatsheet.md                          ← Quick reference for daily use
└── faq.md                                 ← 70+ answered questions
```

---

## Module Overview

### [Module 00 — Lab Environment Setup](./00-setup-lab-environment.md)
Build a repeatable, rootless Podman-based lab on RHEL 10. Spin up one-, two-,
and three-node topologies using UBI 10 containers running systemd and firewalld.
Every subsequent module's lab runs in this environment.

### [Module 01 — Introduction and Architecture](./01-introduction-and-architecture.md)
Understand what firewalld is, where it fits in the Linux networking stack, and
the critical two-layer model (runtime vs permanent) that governs every
`firewall-cmd` operation you will ever run.

### [Module 02 — nftables Fundamentals](./02-nftables-fundamentals.md)
RHEL 10 defaults to nftables. Learn tables, chains, rules, sets, and maps from
scratch using the `nft` CLI — then see exactly how firewalld translates its
configuration into nftables rules. This module is the foundation for all
advanced troubleshooting.

### [Module 03 — Zones and the Trust Model](./03-zones-and-trust-model.md)
Zones are firewalld's core abstraction. Learn every predefined zone, how traffic
is assigned to zones, zone binding precedence, and how to create custom zones for
your specific network topology.

### [Module 04 — Services, Ports, and Protocols](./04-services-ports-and-protocols.md)
Open and close access using named service definitions, raw ports, port ranges,
and protocol specifics including ICMP. Learn to create custom service XML files
for your own applications.

### [Module 05 — Policies and Inter-Zone Routing](./05-policies-and-inter-zone-routing.md)
Zones alone can't control traffic *between* zones. Policies add direction,
priority, and targets to inter-zone flows. This module also covers Policy Sets —
new in firewalld 2.4.0 / RHEL 10 — which provide one-command configurations for
common scenarios like gateways.

### [Module 06 — Rich Rules](./06-rich-rules.md)
The rich rule language gives you surgical control: match on source/destination
address, port, service, ICMP type, and more — then accept, reject, drop, log, or
audit. Covers priority ordering and temporary timeout rules.

### [Module 07 — NAT, Masquerading, and Port Forwarding](./07-nat-masquerading-and-port-forwarding.md)
Build routers and gateways. Understand SNAT (masquerading) and DNAT (port
forwarding) in depth — including the `StrictForwardPorts` option that governs
how container-published ports interact with your firewall.

### [Module 08 — Container Integration](./08-container-integration.md)
Rootless Podman is the default container runtime on RHEL 10. This module
explains how Podman's networking (CNI/Netavark) interacts with firewalld in both
seamless and strict modes, how to own firewall rules for containers, and the
differences between rootless and rootful networking.

### [Module 09 — IP Sets and Dynamic Filtering](./09-ipsets-and-dynamic-filtering.md)
IP sets let you match thousands of addresses in a single rule. Build dynamic
block lists with automatic timeout expiry, geo-blocking pipelines, and efficient
DDoS response tools using `hash:ip`, `hash:net`, and `hash:mac` set types.

### [Module 10 — Logging, Troubleshooting, and Debugging](./10-logging-troubleshooting-and-debugging.md)
A systematic methodology for diagnosing firewall issues: log denied traffic,
read nftables counters, diff runtime vs permanent config, trace policies, and
resolve the most common real-world failure modes.

### [Module 11 — Lockdown Mode and Hardening](./11-lockdown-mode-and-hardening.md)
Prevent unauthorized firewall changes with lockdown mode. Integrate with SELinux,
RHEL cryptographic policies, and compliance scanning considerations for
production-hardened systems.

### [Module 12 — Direct Rules and Advanced nftables](./12-direct-rules-and-advanced-nftables.md)
When firewalld's abstractions aren't enough: direct rules, raw nftables
integration, chain ordering, and flowtables for software-accelerated packet
forwarding. Covers risks and safe usage patterns.

### [Module 13 — Capstone Project](./13-capstone-project.md)
Design and implement a full three-tier application firewall: frontend in a DMZ,
backend in an internal zone, database isolated. Guided from design to
implementation with full explanation of every decision.

---

## Quick Reference Files

- **[cheatsheet.md](./cheatsheet.md)** — Every common `firewall-cmd` invocation
  grouped by task, with nftables inspection commands. Print it. Keep it open.
- **[faq.md](./faq.md)** — 70+ questions answered, from "what is a zone?" to
  "why does my container lose internet after a firewall reload?"

---

## Prerequisites

### System Prerequisites
- RHEL 10 host (physical, VM, or cloud instance) — or any modern Linux host
  capable of running rootless Podman (Fedora 39+, RHEL 9+, Ubuntu 22.04+)
- `podman` version 4.0 or later
- `podman-compose` or `podman network` CLI access
- `nft` CLI tool (`nftables` package)
- `firewalld` package (installed but labs run *inside* containers)
- `curl`, `nc` (netcat), and `ping` available on the host

### Knowledge Prerequisites
- Linux command line: navigate directories, edit files, manage services with
  `systemctl`, read `journalctl` output
- Networking basics: IP addresses, subnets (CIDR notation), ports, TCP vs UDP,
  what a packet is
- No firewall experience required

### Installing Prerequisites on RHEL 10

```bash
# Podman (usually pre-installed on RHEL 10)
sudo dnf install -y podman podman-compose

# nftables tools (for inspecting what firewalld generates)
sudo dnf install -y nftables

# Useful network testing tools
sudo dnf install -y nmap-ncat iputils bind-utils
```

---

## How to Use This Course

### Recommended Path (Linear)
Work through modules 00 → 13 in order. Each module builds on the previous.
The lab environment in module 00 is required for all subsequent labs.

### Reference Path (Non-Linear)
Already know the basics? Use the module overview above to jump to what you need.
Keep `cheatsheet.md` and `faq.md` open as you work.

### Lab Convention

Throughout this course, lab steps follow this convention:

```
🔧 LAB STEP
```
Indicates an action you perform.

```
💡 CONCEPT CHECK
```
A question or observation to solidify understanding before moving on.

```
⚠️  IMPORTANT
```
A warning about a common mistake or destructive action.

```
📝 NOTE
```
Context, background, or a cross-reference to another module.

---

## A Note on RHEL 10 Specifics

This course targets **RHEL 10** specifically. Key differences from RHEL 9 that
affect firewalld behaviour:

| Topic | RHEL 9 | RHEL 10 |
|-------|--------|---------|
| Default packet filter | iptables (legacy) | **nftables only** |
| `iptables` command | Available (legacy) | Deprecated / removed |
| Container runtime | Podman 4.x | **Podman 5.x** |
| Container networking | CNI plugins | **Netavark + Aardvark** |
| `firewall-config` GUI | Available | Removed |
| Policy Sets | Not available | **Available (firewalld 2.4+)** |
| StrictForwardPorts | Not available | **Available** |
| Flowtables | Experimental | **Supported** |

Where behaviour differs between RHEL 9 and RHEL 10, this course notes it
explicitly with a `> RHEL 10` callout.

---

## Conventions Used in This Course

- Shell commands are shown with a `$` prefix for regular user and `#` for root:
  ```bash
  $ firewall-cmd --get-default-zone      # as regular user
  # firewall-cmd --permanent --reload    # as root
  ```
- Container node names follow a consistent naming scheme:
  - `node1` — the primary node (usually the firewall/gateway)
  - `node2` — the secondary node (usually a server or client)
  - `node3` — the tertiary node (used in multi-zone labs)
- All file paths are absolute.
- All `firewall-cmd` examples show both runtime and permanent forms where
  relevant.

---

## Feedback and Errata

This course targets the RHEL 10 GA release. As firewalld evolves, some commands
or behaviours may change. Always cross-reference against:

- `man firewall-cmd` — the authoritative reference
- `man firewalld.zones`, `man firewalld.richlanguage`, `man firewalld.policies`
- [https://firewalld.org/documentation/](https://firewalld.org/documentation/)
- [RHEL 10 Security Guide — Configuring firewalls](https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/10/)

---

*Let's build a thorough understanding — concept by concept, command by command.*

**Start with [Module 00 — Lab Environment Setup →](./00-setup-lab-environment.md)**

# Glossary

The words lattice uses, and what they mean here.

**Subnet**: a network in CIDR notation, IPv4 or IPv6, e.g. `10.10.0.0/22`. The CIDR is unique.

**Parent**: the smallest subnet of the same IP version that contains a subnet. Worked out from the CIDRs, never stored (see [ADR 0001](docs/adr/0001-derived-subnet-hierarchy.md)). A subnet without a parent is a top-level subnet.

**Child**: a subnet whose parent is this one. Two CIDR blocks always either nest or don't overlap at all, so subnets form a tree.

**Allocated**: the share of a subnet's range taken up by its children.

**Free block**: a part of a subnet that no child covers, given as the largest CIDRs that fit. "Next free" is the first free block of a chosen size.

**Address**: a documented IP address. It belongs to the most specific subnet that contains it, has a status (`in-use`, `reserved`, `dhcp`, `available`, `blocked`, `deprecated`) and optional hostname, MAC, owner and tags.

**DHCP range**: a pool inside a subnet that the router hands out. Next free address skips it.

**Discovery**: a host a scan or connector saw on the network. Documented or not, it updates `last_seen`.

**Drift**: where the documentation and the network disagree: undocumented hosts, in-use addresses that went quiet for `STALE_DAYS` (offline), and conflicts (duplicate MAC or hostname, MAC mismatch, static address inside a DHCP range).

**VLAN**: a VLAN ID (1–4094) with a name, optionally per site. A subnet links to at most one.

**Tag**: a free label on subnets and addresses. Names are unique regardless of case.

**Change**: one recorded create, update or delete, with who made it (a user, or `system` for scans and connectors), when, and the old and new value of each field. Secrets are recorded only as "changed".

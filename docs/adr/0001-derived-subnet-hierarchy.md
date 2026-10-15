# 1. Subnet parents are derived, not stored

Date: 2026-10-15. Status: accepted.

## Context

Subnets need a tree: a /16 for the lab with /24s inside, free space between them, and the addresses of a child listed under the child. The usual way is a `parent_id` column, like phpIPAM's `masterSubnetId`.

A stored parent can disagree with the CIDRs. It goes wrong when a CIDR is edited, when a subnet is inserted between two existing levels, when a JSON or CSV import arrives in any order, or when someone sets it by hand. Every one of those paths would need code to re-parent, and the bugs would be silent.

## Decision

lattice stores no parent. When subnets are listed, it sorts them by (version, network address, prefix length) and walks the list once with a stack; the parent of each subnet is the nearest enclosing one. This is O(n log n) and takes milliseconds for thousands of subnets. Free blocks are the subnet minus its direct children (`ipaddress.address_exclude`, then `collapse_addresses`).

Two CIDR blocks always either nest or are disjoint, and an exact duplicate is refused, so containment is always a tree.

## Consequences

- The tree is always right: there is nothing to keep in sync after an edit or import.
- You cannot put a subnet "under" one that doesn't contain it, for grouping by site say. Use tags, VLANs or the environment field for that.
- Addresses do belong to one stored subnet, so creating or deleting a child moves the affected addresses explicitly (`app/hierarchy.py`).
- Queries that need the tree compute it in Python rather than in SQL. If lattice ever needs it inside the database, Postgres `inet` containment operators (`<<`) and a GiST index can do the same without a column.

"""Subnet nesting, derived from the CIDRs rather than stored.

A subnet's parent is the most specific other subnet of the same IP version
that contains it. Nothing is persisted, so a changed CIDR can never leave a
stale parent behind (see docs/adr/0001-derived-subnet-hierarchy.md).
"""
import ipaddress

from app import db
from app.models import IP, DhcpRange, Discovery, Subnet


def _key(subnet):
    net = subnet.network
    return (net.version, int(net.network_address), net.prefixlen)


def tree(subnets):
    """{subnet_id: {'parent_id', 'depth', 'children'}} for the given subnets.

    Sorted by address with shorter prefixes first, every subnet comes right
    after its ancestors, so one stack walk finds each parent.
    """
    out, stack = {}, []
    for s in sorted(subnets, key=_key):
        net = s.network
        while stack and not (stack[-1].network.version == net.version and net.subnet_of(stack[-1].network)):
            stack.pop()
        parent = stack[-1] if stack else None
        out[s.id] = {'parent_id': parent.id if parent else None, 'depth': len(stack), 'children': 0,
                     'allocated': 0}
        if parent:
            out[parent.id]['children'] += 1
            out[parent.id]['_space'] = out[parent.id].get('_space', 0) + net.num_addresses
        stack.append(s)
    # Share of a container's range taken by its child subnets
    for s in subnets:
        space = out[s.id].pop('_space', 0)
        out[s.id]['allocated'] = round(space / s.network.num_addresses * 100, 1) if space else 0
    return out


def ordered(subnets):
    return sorted(subnets, key=_key)


def parent_of(subnet, candidates=None):
    """Most specific subnet that contains this one, or None."""
    net = subnet.network
    best = None
    for other in candidates if candidates is not None else Subnet.query.all():
        if other.id == subnet.id or other.network.version != net.version:
            continue
        if net.subnet_of(other.network) and net != other.network:
            if best is None or other.network.prefixlen > best.network.prefixlen:
                best = other
    return best


def children_of(subnet):
    """Direct children: subnets whose parent is this one."""
    everything = Subnet.query.all()
    links = tree(everything)
    return [s for s in ordered(everything) if links[s.id]['parent_id'] == subnet.id]


def free_blocks(subnet, prefix=None, limit=8):
    """Space in the subnet not taken by its direct children.

    Returns the free ranges as the largest CIDRs that fit, the first `limit`
    candidates of size `prefix`, and the number of free addresses.
    """
    net = subnet.network
    free = [net]
    for child in children_of(subnet):
        rest = []
        for block in free:
            if child.network.subnet_of(block):
                rest.extend(block.address_exclude(child.network))
            else:
                rest.append(block)
        free = rest
    free = sorted(ipaddress.collapse_addresses(free), key=lambda n: int(n.network_address))
    nxt = []
    if prefix is not None:
        for block in free:
            if block.prefixlen > prefix:
                continue
            for candidate in block.subnets(new_prefix=prefix):
                nxt.append(str(candidate))
                if len(nxt) >= limit:
                    break
            if len(nxt) >= limit:
                break
    return {
        'free': [str(b) for b in free[:200]],
        'next': nxt,
        'free_addresses': sum(b.num_addresses for b in free),
    }


def move_into_child(child):
    """After creating a subnet: documented addresses, discoveries and DHCP
    ranges of the parent that fall inside it move down. Returns the count of
    moved addresses."""
    parent = parent_of(child)
    if not parent:
        return 0
    net = child.network
    inside = lambda a: ipaddress.ip_address(a) in net  # noqa: E731
    moved = 0
    for ip in IP.query.filter_by(subnet_id=parent.id).all():
        if inside(ip.address):
            ip.subnet_id = child.id
            moved += 1
    for d in Discovery.query.filter_by(subnet_id=parent.id).all():
        if inside(d.address):
            d.subnet_id = child.id
    for r in DhcpRange.query.filter_by(subnet_id=parent.id).all():
        if inside(r.start_address) and inside(r.end_address):
            r.subnet_id = child.id
    return moved


def move_to_parent(subnet):
    """Before deleting a subnet: its addresses and discoveries go to the
    parent, if there is one. Duplicates already in the parent are dropped.
    Returns (parent, moved)."""
    parent = parent_of(subnet)
    if not parent:
        return None, 0
    taken = {a for (a,) in db.session.query(IP.address).filter_by(subnet_id=parent.id)}
    seen = {a for (a,) in db.session.query(Discovery.address).filter_by(subnet_id=parent.id)}
    moved = 0
    for ip in IP.query.filter_by(subnet_id=subnet.id).all():
        if ip.address not in taken:
            ip.subnet_id = parent.id
            moved += 1
    for d in Discovery.query.filter_by(subnet_id=subnet.id).all():
        if d.address not in seen:
            d.subnet_id = parent.id
    db.session.flush()
    db.session.expire(subnet)  # forget the moved rows so the cascade only takes what's left
    return parent, moved

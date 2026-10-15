"""Input validation and normalisation shared by every write path.

Create, update, bulk add, import, scan import and connector sync all go
through these functions, so stored addresses are always canonical.
"""
import ipaddress
import re

from app import db
from app.models import IP_STATUSES, Subnet, Vlan

MAX_TEXT = 255
ENV_RE = re.compile(r'^[A-Za-z0-9 _.-]{1,50}$')


class ValidationError(ValueError):
    """Raised with a message that is safe to show to the user."""


def normalize_cidr(value):
    try:
        return str(ipaddress.ip_network(str(value).strip(), strict=False))
    except ValueError:
        raise ValidationError(f'Invalid CIDR: {value}')


def normalize_ip(value, field='address'):
    try:
        return str(ipaddress.ip_address(str(value).strip()))
    except ValueError:
        raise ValidationError(f'Invalid {field}: {value}')


def normalize_mac(value):
    if not value:
        return None
    digits = re.sub(r'[^0-9A-Fa-f]', '', str(value)).upper()
    if len(digits) != 12:
        raise ValidationError(f'Invalid MAC address: {value}')
    return ':'.join(digits[i:i + 2] for i in range(0, 12, 2))


def _text(value, field, max_len=MAX_TEXT):
    if value is None:
        return None
    if not isinstance(value, (str, int, float)):
        raise ValidationError(f'{field} must be text')
    value = str(value).strip()
    if len(value) > max_len:
        raise ValidationError(f'{field} is longer than {max_len} characters')
    return value or None


def _optional_ip(value, field):
    return normalize_ip(value, field) if value not in (None, '') else None


def subnet_fields(data, partial=False):
    """Validate subnet input and return the fields to set."""
    if not isinstance(data, dict):
        raise ValidationError('Expected a JSON object')
    out = {}
    if not partial or 'name' in data:
        out['name'] = _text(data.get('name'), 'name')
        if not out['name']:
            raise ValidationError('name is required')
    if not partial or 'cidr' in data:
        if not data.get('cidr'):
            raise ValidationError('cidr is required')
        out['cidr'] = normalize_cidr(data['cidr'])
    for field in ('gateway', 'dns_primary', 'dns_secondary'):
        if field in data:
            out[field] = _optional_ip(data[field], field)
    # A VLAN by id, or by number for older clients and imports (found or created)
    if 'vlan_id' in data:
        out['_vlan_id'] = _optional_int(data['vlan_id'], 'vlan_id')
    elif 'vlan' in data:
        vid = _optional_int(data['vlan'], 'vlan')
        if vid is not None and not 1 <= vid <= 4094:
            raise ValidationError('vlan must be between 1 and 4094')
        out['_vlan_vid'] = (vid, str(data.get('vlan_site') or '')) if vid is not None else None
    if 'environment' in data:
        env = _text(data['environment'], 'environment', 50)
        if env and not ENV_RE.match(env):
            raise ValidationError('environment may only contain letters, numbers, spaces and - _ .')
        out['environment'] = env
    for field in ('location',):
        if field in data:
            out[field] = _text(data[field], field)
    if 'description' in data:
        out['description'] = _text(data['description'], 'description', 5000)
    if 'tags' in data:
        out['_tags'] = tag_names(data['tags'])
    if 'scan_enabled' in data:
        value = data['scan_enabled']
        out['scan_enabled'] = None if value is None else bool(value)
    return out


def _optional_int(value, field):
    if value in (None, ''):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValidationError(f'{field} must be a number')


def tag_names(value):
    """Clean tag input: a list or comma/semicolon-separated text, at most 20."""
    items = value or []
    if isinstance(items, str):
        items = re.split(r'[,;]', items)
    if not isinstance(items, list):
        raise ValidationError('tags must be a list')
    names, seen = [], set()
    for item in items:
        name = _text(item, 'tag', 50)
        if name and name.lower() not in seen:
            seen.add(name.lower())
            names.append(name)
    if len(names) > 20:
        raise ValidationError('At most 20 tags')
    return names


def check_subnet(subnet):
    """Checks that need the whole subnet: gateway inside, IPs still inside after a CIDR change."""
    net = ipaddress.ip_network(subnet.cidr)
    if subnet.gateway and ipaddress.ip_address(subnet.gateway) not in net:
        raise ValidationError(f'Gateway {subnet.gateway} is not inside {subnet.cidr}')
    if subnet.id:
        with db.session.no_autoflush:
            _check_contents(subnet, net)


def _check_contents(subnet, net):
    outside = [ip.address for ip in subnet.ips if ipaddress.ip_address(ip.address) not in net]
    if outside:
        raise ValidationError(
            f'{len(outside)} documented address(es) would fall outside {subnet.cidr}, '
            f'e.g. {outside[0]}')
    for r in subnet.dhcp_ranges:
        if not (subnet.contains(r.start_address) and subnet.contains(r.end_address)):
            raise ValidationError(
                f'DHCP range {r.start_address}-{r.end_address} would fall outside {subnet.cidr}')


def ip_fields(data, partial=False):
    """Validate IP input and return the fields to set (address is canonical)."""
    if not isinstance(data, dict):
        raise ValidationError('Expected a JSON object')
    out = {}
    if not partial or 'address' in data:
        if not data.get('address'):
            raise ValidationError('address is required')
        out['address'] = normalize_ip(data['address'])
    if not partial or 'status' in data:
        status = data.get('status') or 'in-use'
        if status not in IP_STATUSES:
            raise ValidationError(f'status must be one of: {", ".join(IP_STATUSES)}')
        out['status'] = status
    if 'mac_address' in data:
        out['mac_address'] = normalize_mac(data['mac_address'])
    for field in ('hostname', 'fqdn', 'owner', 'department'):
        if field in data:
            out[field] = _text(data[field], field)
    for field in ('device_type', 'manufacturer', 'model', 'serial_number'):
        if field in data:
            out[field] = _text(data[field], field, 100)
    for field in ('description', 'notes'):
        if field in data:
            out[field] = _text(data[field], field, 5000)
    if 'tags' in data:
        out['_tags'] = tag_names(data['tags'])
    return out


def check_ip_in_subnet(address, subnet):
    if not subnet.contains(address):
        raise ValidationError(f'{address} is not inside {subnet.cidr}')


def dhcp_range_fields(data, subnet, exclude_id=None):
    if not isinstance(data, dict):
        raise ValidationError('Expected a JSON object')
    start = normalize_ip(data.get('start') or '', 'start address')
    end = normalize_ip(data.get('end') or '', 'end address')
    for addr in (start, end):
        check_ip_in_subnet(addr, subnet)
    lo, hi = int(ipaddress.ip_address(start)), int(ipaddress.ip_address(end))
    if lo > hi:
        raise ValidationError('start must not be after end')
    for r in subnet.dhcp_ranges:
        if r.id != exclude_id and lo <= r.end_int and r.start_int <= hi:
            raise ValidationError(f'Overlaps DHCP range {r.start_address}-{r.end_address}')
    return {
        'start_address': start,
        'end_address': end,
        'description': _text(data.get('description'), 'description'),
    }


def apply(obj, fields):
    """Set validated fields; tags and VLAN references resolve to their rows."""
    from app.catalog import resolve_tags, vlan_by_number
    for key, value in fields.items():
        if key == '_tags':
            obj.tags = resolve_tags(value)
        elif key == '_vlan_id':
            if value is not None and not db.session.get(Vlan, value):
                raise ValidationError('VLAN not found')
            obj.vlan_id = value
        elif key == '_vlan_vid':
            obj.vlan_obj = vlan_by_number(*value) if value is not None else None
        else:
            setattr(obj, key, value)
    return obj


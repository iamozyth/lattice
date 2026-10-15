"""Bulk edits and CSV import/export for addresses and subnets."""
import csv
import io
from datetime import datetime

from flask import Response, request
from flask_openapi3 import APIBlueprint, Tag as ApiTag

from app import db, hierarchy, limiter
from app.auth import require_role
from app.catalog import resolve_tags, tag_filter
from app.models import IP, Subnet
from app.validation import (ValidationError, apply, check_ip_in_subnet, check_subnet, ip_fields,
                            normalize_cidr, normalize_ip, subnet_fields, tag_names)

bulk_bp = APIBlueprint('bulk', __name__, url_prefix='/api')
tag_api = ApiTag(name='Bulk and CSV')

MAX_BULK = 1000
MAX_ROWS = 10000
BULK_FIELDS = ('status', 'owner', 'department', 'device_type')

IP_COLUMNS = ['address', 'subnet', 'status', 'hostname', 'fqdn', 'mac_address', 'device_type', 'manufacturer',
              'model', 'serial_number', 'owner', 'department', 'tags', 'description', 'notes', 'last_seen']
SUBNET_COLUMNS = ['name', 'cidr', 'vlan', 'vlan_name', 'gateway', 'dns_primary', 'dns_secondary', 'location',
                  'environment', 'tags', 'description']

# Header names from phpIPAM, NetBox and common spreadsheets
ALIASES = {
    'ip': 'address', 'ip_addr': 'address', 'ip_address': 'address', 'ipaddress': 'address', 'addr': 'address',
    'host': 'hostname', 'name': 'hostname', 'dns_name': 'fqdn', 'mac': 'mac_address', 'macaddress': 'mac_address',
    'state': 'status', 'tag': 'tags', 'note': 'notes', 'comment': 'notes', 'comments': 'notes',
    'vendor': 'manufacturer', 'serial': 'serial_number', 'device': 'device_type', 'type': 'device_type',
    'section': None, 'id': None,
    'subnet_cidr': 'subnet', 'prefix': 'subnet', 'network': 'subnet',
}
SUBNET_ALIASES = {'prefix': 'cidr', 'subnet': 'cidr', 'network': 'cidr', 'description': 'description',
                  'vlan_id': 'vlan', 'vid': 'vlan', 'tag': 'tags', 'site': 'location', 'name': 'name', 'id': None}
STATUS_ALIASES = {'used': 'in-use', 'active': 'in-use', 'online': 'in-use', 'free': 'available',
                  'reserved': 'reserved', 'dhcp': 'dhcp', 'offline': 'deprecated'}


# ---------------------------------------------------------------------------
# Bulk edit
# ---------------------------------------------------------------------------

def _ids(data):
    ids = data.get('ids')
    if not isinstance(ids, list) or not ids or not all(isinstance(i, int) for i in ids):
        raise ValidationError('ids must be a non-empty list of address IDs')
    if len(ids) > MAX_BULK:
        raise ValidationError(f'At most {MAX_BULK} addresses at once')
    return ids


@bulk_bp.post('/ips/bulk-update', tags=[tag_api])
@require_role('editor')
@limiter.limit('30 per minute')
def bulk_update():
    """Set status, owner, department or device type, and add or remove tags, on many addresses."""
    data = request.get_json(silent=True) or {}
    ids = _ids(data)
    fields_in = data.get('set') or {}
    if not isinstance(fields_in, dict) or set(fields_in) - set(BULK_FIELDS):
        raise ValidationError(f'set may only contain: {", ".join(BULK_FIELDS)}')
    fields = ip_fields(fields_in, partial=True)
    add = resolve_tags(tag_names(data.get('add_tags') or []))
    remove = {n.lower() for n in tag_names(data.get('remove_tags') or [])}
    ips = IP.query.filter(IP.id.in_(ids)).all()
    for ip in ips:
        apply(ip, fields)
        ip.tags = [t for t in ip.tags if t.name.lower() not in remove] + [t for t in add if t not in ip.tags]
    db.session.commit()
    return {'updated': len(ips)}


@bulk_bp.post('/ips/bulk-delete', tags=[tag_api])
@require_role('editor')
@limiter.limit('30 per minute')
def bulk_delete():
    ids = _ids(request.get_json(silent=True) or {})
    ips = IP.query.filter(IP.id.in_(ids)).all()
    for ip in ips:
        db.session.delete(ip)
    db.session.commit()
    return {'deleted': len(ips)}


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

def _safe(value):
    """Spreadsheets run cells that start with = + - @ as formulas; quote them."""
    if value is None:
        return ''
    text = value.isoformat() if isinstance(value, datetime) else str(value)
    return f"'{text}" if text[:1] in ('=', '+', '-', '@', '\t', '\r') else text


def _csv_response(columns, rows, kind):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_safe(row.get(c)) for c in columns])
    stamp = datetime.utcnow().strftime('%Y%m%d-%H%M')
    return Response(buf.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename=lattice-{kind}-{stamp}.csv'})


@bulk_bp.get('/export.csv', tags=[tag_api])
@require_role('viewer')
def export_csv():
    """type=ips (with the address list filters) or type=subnets (tag, vlan_id)."""
    from app.routes import ip_query
    kind = request.args.get('type', 'ips')
    if kind == 'ips':
        rows = []
        for ip in ip_query(request.args).limit(200000):
            row = {k: getattr(ip, k) for k in IP.FIELDS}
            row.update(subnet=ip.subnet.cidr, tags=';'.join(t.name for t in ip.tags), last_seen=ip.last_seen)
            rows.append(row)
        return _csv_response(IP_COLUMNS, rows, 'addresses')
    if kind == 'subnets':
        query = Subnet.query
        if request.args.get('tag'):
            query = tag_filter(query, Subnet, request.args['tag'])
        if request.args.get('vlan_id', '').isdigit():
            query = query.filter(Subnet.vlan_id == int(request.args['vlan_id']))
        rows = []
        for s in hierarchy.ordered(query.all()):
            v = s.vlan_obj
            rows.append({c: getattr(s, c, None) for c in SUBNET_COLUMNS if c not in ('vlan', 'vlan_name', 'tags')}
                        | {'vlan': v.vid if v else None, 'vlan_name': v.name if v else None,
                           'tags': ';'.join(t.name for t in s.tags)})
        return _csv_response(SUBNET_COLUMNS, rows, 'subnets')
    raise ValidationError('type must be ips or subnets')


# ---------------------------------------------------------------------------
# CSV import
# ---------------------------------------------------------------------------

def _read(text, aliases, known):
    """Rows as dicts keyed by our field names; empty cells left out."""
    if not isinstance(text, str) or not text.strip():
        raise ValidationError('The file is empty')
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=',;\t')
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text.lstrip('﻿')), dialect)
    header = next(reader, None) or []
    keys = []
    for h in header:
        key = h.strip().lower().replace(' ', '_').replace('-', '_')
        key = aliases.get(key, key) if key in aliases else key
        keys.append(key if key in known else None)
    rows = []
    for line, cells in enumerate(reader, start=2):
        if not any(c.strip() for c in cells):
            continue
        if len(rows) >= MAX_ROWS:
            raise ValidationError(f'At most {MAX_ROWS} rows per import')
        row = {}
        for key, cell in zip(keys, cells):
            cell = cell.strip()
            if key and cell:
                if cell[:2] in ("'=", "'+", "'-", "'@"):  # undo our own export quoting
                    cell = cell[1:]
                row[key] = cell
        rows.append((line, row))
    return keys, rows


def _subnet_by(value, subnets):
    try:
        cidr = normalize_cidr(value)
        return next((s for s in subnets if s.cidr == cidr), None)
    except ValidationError:
        return next((s for s in subnets if s.name.lower() == value.lower()), None)


def _plan_ips(rows):
    from app.routes import _find_subnet
    subnets = Subnet.query.all()
    seen = set()
    plan = []
    for line, row in rows:
        entry = {'line': line, 'address': row.get('address')}
        try:
            if 'status' in row:
                row['status'] = STATUS_ALIASES.get(row['status'].lower(), row['status'].lower())
            address = normalize_ip(row.get('address') or '')
            subnet = _subnet_by(row['subnet'], subnets) if row.get('subnet') else _find_subnet(address)
            if not subnet:
                raise ValidationError(f'{address} is not inside any subnet' if not row.get('subnet')
                                      else f'Subnet {row["subnet"]} not found')
            check_ip_in_subnet(address, subnet)
            if (subnet.id, address) in seen:
                raise ValidationError(f'{address} appears twice in the file')
            seen.add((subnet.id, address))
            values = {k: v for k, v in row.items() if k not in ('subnet', 'last_seen')}
            existing = IP.query.filter_by(subnet_id=subnet.id, address=address).first()
            if existing:
                fields = ip_fields(values, partial=True)
                changes = {}
                for key, value in fields.items():
                    if key == '_tags':
                        if sorted(t.lower() for t in value) != sorted(t.name.lower() for t in existing.tags):
                            changes['tags'] = value
                    elif key != 'address' and getattr(existing, key) != value:
                        changes[key] = value
                entry.update(action='update' if changes else 'unchanged', changes=changes,
                             _obj=existing, _fields=fields)
            else:
                fields = ip_fields(values)
                entry.update(action='create', subnet=subnet.cidr, _subnet=subnet, _fields=fields)
            entry['address'] = address
        except ValidationError as e:
            entry.update(action='error', error=str(e))
        plan.append(entry)
    return plan


def _plan_subnets(rows):
    plan = []
    for line, row in rows:
        entry = {'line': line, 'name': row.get('name'), 'cidr': row.get('cidr')}
        try:
            cidr = normalize_cidr(row.get('cidr') or '')
            existing = Subnet.query.filter_by(cidr=cidr).first()
            fields = subnet_fields(row, partial=bool(existing))
            entry['cidr'] = cidr
            if existing:
                changes = {k: v for k, v in fields.items()
                           if not k.startswith('_') and k != 'cidr' and getattr(existing, k) != v}
                if '_tags' in fields and sorted(t.lower() for t in fields['_tags']) != sorted(t.name.lower() for t in existing.tags):
                    changes['tags'] = fields['_tags']
                if '_vlan_vid' in fields and (fields['_vlan_vid'] or (None,))[0] != (existing.vlan_obj.vid if existing.vlan_obj else None):
                    changes['vlan'] = fields['_vlan_vid'][0] if fields['_vlan_vid'] else None
                entry.update(action='update' if changes else 'unchanged', changes=changes, _obj=existing, _fields=fields)
            else:
                if Subnet.query.filter_by(name=fields['name']).first():
                    raise ValidationError(f'The name {fields["name"]} is already used by another subnet')
                entry.update(action='create', _fields=fields)
        except ValidationError as e:
            entry.update(action='error', error=str(e))
        plan.append(entry)
    return plan


@bulk_bp.post('/import/csv', tags=[tag_api])
@require_role('editor')
@limiter.limit('20 per minute')
def import_csv():
    """Body {csv: "..."}; type=ips|subnets. dry_run=1 previews row by row without saving.

    Existing rows (by address within its subnet, or by CIDR) are updated; empty cells
    leave values unchanged. Rows with errors block the import; nothing is saved.
    """
    data = request.get_json(silent=True) or {}
    kind = request.args.get('type', 'ips')
    dry = request.args.get('dry_run', '').lower() in ('1', 'true')
    if kind == 'ips':
        keys, rows = _read(data.get('csv'), ALIASES, set(IP_COLUMNS))
        if 'address' not in keys:
            raise ValidationError('The file needs an address column (also accepted: ip, ip_addr, ip address)')
        plan = _plan_ips(rows)
    elif kind == 'subnets':
        keys, rows = _read(data.get('csv'), SUBNET_ALIASES, set(SUBNET_COLUMNS))
        if 'cidr' not in keys or 'name' not in keys:
            raise ValidationError('The file needs name and cidr columns')
        plan = _plan_subnets(rows)
    else:
        raise ValidationError('type must be ips or subnets')

    counts = {k: sum(1 for p in plan if p['action'] == k) for k in ('create', 'update', 'unchanged', 'error')}
    public = [{k: v for k, v in p.items() if not k.startswith('_')} for p in plan]
    if dry:
        return {'rows': public[:2000], 'counts': counts}
    errors = [p for p in plan if p['action'] == 'error']
    if errors:
        first = errors[0]
        raise ValidationError(f'{len(errors)} row(s) have errors, e.g. line {first["line"]}: {first["error"]}. Nothing was imported.')

    for p in plan:
        if p['action'] == 'create' and kind == 'ips':
            db.session.add(apply(IP(subnet_id=p['_subnet'].id), p['_fields']))
        elif p['action'] == 'create':
            subnet = apply(Subnet(), p['_fields'])
            check_subnet(subnet)
            db.session.add(subnet)
            db.session.flush()
            hierarchy.move_into_child(subnet)
        elif p['action'] == 'update':
            fields = {k: v for k, v in p['_fields'].items() if k != 'address'}
            apply(p['_obj'], fields)
            if kind == 'subnets':
                check_subnet(p['_obj'])
    db.session.commit()
    return {'rows': public[:2000], 'counts': counts}


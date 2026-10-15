"""Core API: subnets, IPs, DHCP ranges, subnet map, lookup, import/export."""
import ipaddress
from collections import defaultdict
from datetime import datetime

from flask import Blueprint, jsonify, redirect, render_template, request
from flask_login import current_user
from flask_openapi3 import APIBlueprint, Tag
from pydantic import BaseModel
from sqlalchemy import cast, func
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.exc import IntegrityError

from app import VERSION, db, hierarchy, limiter
from app.auth import require_role
from app.catalog import tag_filter, vlan_by_number
from app.models import IP, USED_STATUSES, Discovery, DhcpRange, Subnet, Tag, Vlan
from app.scanner import scan_jobs
from app.validation import (ValidationError, apply, check_ip_in_subnet, check_subnet,
                            dhcp_range_fields, ip_fields, normalize_ip,
                            subnet_fields)

api_bp = APIBlueprint('api', __name__, url_prefix='/api')
main_bp = Blueprint('main', __name__)

tag_subnets = Tag(name='Subnets')
tag_ips = Tag(name='IPs')
tag_data = Tag(name='Import/Export')

MAX_BULK = 1000
MAX_MAP_CELLS = 1024


class SubnetPath(BaseModel):
    subnet_id: int


class IPPath(BaseModel):
    ip_id: int


class RangePath(BaseModel):
    range_id: int


class LookupPath(BaseModel):
    address: str


def _json():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError('Expected a JSON object body')
    return data


def _int_arg(name, default, lo, hi):
    try:
        value = int(request.args.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(lo, min(hi, value))


def _like(term):
    escaped = term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    return f'%{escaped}%'


def _subnet_or_404(subnet_id):
    subnet = db.session.get(Subnet, subnet_id)
    if not subnet:
        return None, ({'error': 'Subnet not found'}, 404)
    return subnet, None


def _ip_counts(subnet_ids=None):
    """{subnet_id: (documented, used)} in one query."""
    q = db.session.query(
        IP.subnet_id, func.count(IP.id),
        func.count(IP.id).filter(IP.status.in_(USED_STATUSES)),
    ).group_by(IP.subnet_id)
    if subnet_ids is not None:
        q = q.filter(IP.subnet_id.in_(subnet_ids))
    return {sid: (total, used) for sid, total, used in q}


def _subnet_dict(subnet, counts=None):
    if counts is None:
        counts = _ip_counts([subnet.id])
    total, used = counts.get(subnet.id, (0, 0))
    return subnet.to_dict(used_count=used, ip_count=total)


def _with_parent(subnet, data):
    everything = Subnet.query.all()
    parent = hierarchy.parent_of(subnet, everything)
    data['inside'] = {'id': parent.id, 'name': parent.name, 'cidr': parent.cidr} if parent else None
    links = hierarchy.tree(everything)
    data.update({k: links[subnet.id][k] for k in ('depth', 'children', 'allocated')})
    return data


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@main_bp.route('/')
def index():
    if not current_user.is_authenticated:
        return redirect('/login')
    return render_template('index.html', version=VERSION)


@main_bp.route('/login')
def login_page():
    if current_user.is_authenticated:
        return redirect('/')
    return render_template('login.html', version=VERSION)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@api_bp.get('/stats', tags=[tag_subnets])
@require_role('viewer')
def stats():
    subnets = Subnet.query.all()
    counts = _ip_counts()
    capacity = sum(s.usable_count for s in subnets if s.network.version == 4)
    used_v4 = sum(counts.get(s.id, (0, 0))[1] for s in subnets if s.network.version == 4)
    by_status = dict(db.session.query(IP.status, func.count(IP.id)).group_by(IP.status).all())
    undocumented = (db.session.query(func.count(Discovery.id))
                    .outerjoin(IP, (IP.subnet_id == Discovery.subnet_id) & (IP.address == Discovery.address))
                    .filter(IP.id.is_(None), Discovery.ignored.is_(False)).scalar())
    return {
        'subnets': len(subnets),
        'ips': sum(total for total, _ in counts.values()),
        'ipv4_capacity': capacity,
        'ipv4_used': used_v4,
        'utilization': round(used_v4 / capacity * 100, 1) if capacity else 0,
        'by_status': by_status,
        'undocumented': undocumented,
    }


@api_bp.get('/version', tags=[tag_subnets])
@require_role('viewer')
def version():
    return {'version': VERSION, 'repository': 'https://github.com/iamozyth/lattice'}


# ---------------------------------------------------------------------------
# Subnets
# ---------------------------------------------------------------------------

@api_bp.get('/subnets', tags=[tag_subnets])
@require_role('viewer')
def list_subnets():
    """List subnets. Filters: search, environment, vlan."""
    query = Subnet.query
    search = request.args.get('search', '').strip()[:200]
    if search:
        like = _like(search)
        query = query.filter(
            Subnet.name.ilike(like, escape='\\') | Subnet.cidr.ilike(like, escape='\\')
            | Subnet.description.ilike(like, escape='\\') | Subnet.location.ilike(like, escape='\\')
            | Subnet.tags.any(Tag.name.ilike(like, escape='\\')))
    if request.args.get('environment'):
        query = query.filter(Subnet.environment == request.args['environment'])
    if request.args.get('vlan_id', '').isdigit():
        query = query.filter(Subnet.vlan_id == int(request.args['vlan_id']))
    if request.args.get('vlan', '').isdigit():
        query = query.filter(Subnet.vlan_obj.has(Vlan.vid == int(request.args['vlan'])))
    if request.args.get('tag'):
        query = tag_filter(query, Subnet, request.args['tag'])
    matches = {s.id for s in query.limit(2000)}
    everything = Subnet.query.all()
    links = hierarchy.tree(everything)
    subnets = [s for s in hierarchy.ordered(everything) if s.id in matches]
    counts = _ip_counts([s.id for s in subnets])
    environments = sorted({e for (e,) in db.session.query(Subnet.environment).distinct() if e})
    items = [{**_subnet_dict(s, counts), **links[s.id]} for s in subnets]
    return {'items': items, 'environments': environments}


@api_bp.get('/subnets/<int:subnet_id>', tags=[tag_subnets])
@require_role('viewer')
def get_subnet(path: SubnetPath):
    subnet, err = _subnet_or_404(path.subnet_id)
    if err:
        return err
    return {**_with_parent(subnet, _subnet_dict(subnet)), 'scan_job_id': scan_jobs.running_for(subnet.id)}


@api_bp.post('/subnets', tags=[tag_subnets])
@require_role('editor')
@limiter.limit('60 per minute')
def create_subnet():
    subnet = apply(Subnet(), subnet_fields(_json()))
    check_subnet(subnet)
    db.session.add(subnet)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        return {'error': 'A subnet with this name or CIDR already exists'}, 409
    moved = hierarchy.move_into_child(subnet)
    db.session.commit()
    data = _with_parent(subnet, _subnet_dict(subnet))
    data['moved'] = moved
    return data, 201


@api_bp.put('/subnets/<int:subnet_id>', tags=[tag_subnets])
@require_role('editor')
def update_subnet(path: SubnetPath):
    subnet, err = _subnet_or_404(path.subnet_id)
    if err:
        return err
    apply(subnet, subnet_fields(_json(), partial=True))
    check_subnet(subnet)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return {'error': 'A subnet with this name or CIDR already exists'}, 409
    return _with_parent(subnet, _subnet_dict(subnet))


@api_bp.delete('/subnets/<int:subnet_id>', tags=[tag_subnets])
@require_role('editor')
def delete_subnet(path: SubnetPath):
    subnet, err = _subnet_or_404(path.subnet_id)
    if err:
        return err
    hierarchy.move_to_parent(subnet)  # addresses go up to the parent, if any
    db.session.delete(subnet)
    db.session.commit()
    return '', 204


@api_bp.get('/subnets/<int:subnet_id>/free-blocks', tags=[tag_subnets])
@require_role('viewer')
def free_blocks(path: SubnetPath):
    """Space not taken by child subnets, and the next free blocks of a size."""
    subnet, err = _subnet_or_404(path.subnet_id)
    if err:
        return err
    net = subnet.network
    prefix = request.args.get('prefix', '')
    if prefix:
        if not prefix.isdigit() or not net.prefixlen < int(prefix) <= net.max_prefixlen:
            return {'error': f'prefix must be between /{net.prefixlen + 1} and /{net.max_prefixlen}'}, 400
        prefix = int(prefix)
    return hierarchy.free_blocks(subnet, prefix or None, _int_arg('limit', 8, 1, 64))


@api_bp.get('/subnets/<int:subnet_id>/free', tags=[tag_subnets])
@require_role('viewer')
def free_addresses(path: SubnetPath):
    """Free addresses, skipping network, broadcast, gateway and DHCP pools."""
    subnet, err = _subnet_or_404(path.subnet_id)
    if err:
        return err
    used = {a for (a,) in db.session.query(IP.address).filter_by(subnet_id=subnet.id)}
    addresses = subnet.free_addresses(used, limit=_int_arg('limit', 20, 1, 200))
    return {'next': addresses[0] if addresses else None, 'addresses': addresses}


@api_bp.get('/subnets/<int:subnet_id>/map', tags=[tag_subnets])
@require_role('viewer')
def subnet_map(path: SubnetPath):
    """State of every address, for IPv4 subnets up to /22."""
    subnet, err = _subnet_or_404(path.subnet_id)
    if err:
        return err
    net = subnet.network
    if net.version != 4 or net.num_addresses > MAX_MAP_CELLS:
        return {'error': 'The map is available for IPv4 subnets up to /22'}, 400
    ips = {ip.address: ip for ip in subnet.ips}
    discovered = {d.address: d for d in Discovery.query.filter_by(subnet_id=subnet.id, ignored=False)}
    reserved = subnet.reserved_addresses()
    ranges = [(r.start_int, r.end_int) for r in subnet.dhcp_ranges]
    children = [(c.network, c) for c in hierarchy.children_of(subnet)]
    cells = []
    for addr in net:
        key = str(addr)
        cell = {'address': key}
        ip = ips.get(key)
        child = next((c for cnet, c in children if addr in cnet), None)
        if child:
            cell.update(state='child', child_id=child.id, hostname=f'{child.name} ({child.cidr})')
        elif key == subnet.gateway:
            # Stays a gateway when the router is also documented or seen by a scan
            cell['state'] = 'gateway'
            if ip:
                cell.update(id=ip.id, hostname=ip.hostname)
        elif ip:
            cell.update(state=ip.status, id=ip.id, hostname=ip.hostname)
        elif addr in reserved:
            cell['state'] = 'reserved-net'
        elif key in discovered:
            cell.update(state='undocumented', hostname=discovered[key].hostname)
        else:
            cell['state'] = 'free'
        if any(lo <= int(addr) <= hi for lo, hi in ranges):
            cell['pool'] = True
        if key in discovered:
            cell['seen'] = discovered[key].last_seen.isoformat()
        cells.append(cell)
    return {'subnet_id': subnet.id, 'cidr': subnet.cidr, 'cells': cells}


# ---------------------------------------------------------------------------
# DHCP ranges
# ---------------------------------------------------------------------------

@api_bp.get('/subnets/<int:subnet_id>/dhcp-ranges', tags=[tag_subnets])
@require_role('viewer')
def list_ranges(path: SubnetPath):
    subnet, err = _subnet_or_404(path.subnet_id)
    if err:
        return err
    return {'items': [r.to_dict() for r in subnet.dhcp_ranges]}


@api_bp.post('/subnets/<int:subnet_id>/dhcp-ranges', tags=[tag_subnets])
@require_role('editor')
def create_range(path: SubnetPath):
    subnet, err = _subnet_or_404(path.subnet_id)
    if err:
        return err
    r = DhcpRange(subnet_id=subnet.id, **dhcp_range_fields(_json(), subnet))
    db.session.add(r)
    db.session.commit()
    return r.to_dict(), 201


@api_bp.put('/dhcp-ranges/<int:range_id>', tags=[tag_subnets])
@require_role('editor')
def update_range(path: RangePath):
    r = db.session.get(DhcpRange, path.range_id)
    if not r:
        return {'error': 'DHCP range not found'}, 404
    apply(r, dhcp_range_fields(_json(), r.subnet, exclude_id=r.id))
    db.session.commit()
    return r.to_dict()


@api_bp.delete('/dhcp-ranges/<int:range_id>', tags=[tag_subnets])
@require_role('editor')
def delete_range(path: RangePath):
    r = db.session.get(DhcpRange, path.range_id)
    if not r:
        return {'error': 'DHCP range not found'}, 404
    db.session.delete(r)
    db.session.commit()
    return '', 204


# ---------------------------------------------------------------------------
# IPs
# ---------------------------------------------------------------------------

def _find_subnet(address):
    """Most specific subnet containing the address."""
    return (Subnet.query
            .filter(cast(Subnet.cidr, INET).op('>>=')(cast(address, INET)))
            .order_by(func.masklen(cast(Subnet.cidr, INET)).desc())
            .first())


def _ip_warnings(ip, subnet):
    warnings = []
    if ip.status in ('in-use', 'reserved') and subnet.in_dhcp_range(ip.address):
        warnings.append(f'{ip.address} is inside a DHCP pool')
    if ip.address == subnet.gateway:
        warnings.append(f'{ip.address} is the subnet gateway')
    return warnings


@api_bp.get('/ips', tags=[tag_ips])
@require_role('viewer')
def list_ips():
    """List IPs. Filters: subnet_id, status, tag, vlan_id, search. Paged with page/per_page."""
    query = ip_query(request.args)
    page = _int_arg('page', 1, 1, 100000)
    per_page = _int_arg('per_page', 100, 1, 500)
    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    return {'items': [ip.to_dict() for ip in items], 'total': total, 'page': page,
            'per_page': per_page, 'pages': (total + per_page - 1) // per_page}


def ip_query(args):
    """Addresses matching the list filters, in address order (also used by CSV export)."""
    query = IP.query.join(Subnet)
    if args.get('subnet_id', '').isdigit():
        query = query.filter(IP.subnet_id == int(args['subnet_id']))
    if args.get('status'):
        query = query.filter(IP.status == args['status'])
    if args.get('tag'):
        query = tag_filter(query, IP, args['tag'])
    if args.get('vlan_id', '').isdigit():
        query = query.filter(Subnet.vlan_id == int(args['vlan_id']))
    search = args.get('search', '').strip()[:200]
    if search:
        like = _like(search)
        query = query.filter(
            IP.address.ilike(like, escape='\\') | IP.hostname.ilike(like, escape='\\')
            | IP.fqdn.ilike(like, escape='\\') | IP.mac_address.ilike(like, escape='\\')
            | IP.description.ilike(like, escape='\\') | IP.owner.ilike(like, escape='\\')
            | IP.tags.any(Tag.name.ilike(like, escape='\\'))
            | IP.device_type.ilike(like, escape='\\'))
    return query.order_by(cast(IP.address, INET), IP.id)


@api_bp.get('/ips/<int:ip_id>', tags=[tag_ips])
@require_role('viewer')
def get_ip(path: IPPath):
    ip = db.session.get(IP, path.ip_id)
    if not ip:
        return {'error': 'IP not found'}, 404
    return ip.to_dict()


@api_bp.post('/ips', tags=[tag_ips])
@require_role('editor')
@limiter.limit('120 per minute')
def create_ip():
    """Document an IP. Without subnet_id the most specific matching subnet is used."""
    data = _json()
    fields = ip_fields(data)
    if data.get('subnet_id'):
        subnet = db.session.get(Subnet, data['subnet_id']) if str(data['subnet_id']).isdigit() else None
    else:
        subnet = _find_subnet(fields['address'])
    if not subnet:
        return {'error': 'No matching subnet. Create the subnet first.'}, 400
    check_ip_in_subnet(fields['address'], subnet)
    ip = apply(IP(subnet_id=subnet.id), fields)
    db.session.add(ip)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return {'error': f'{fields["address"]} is already documented in {subnet.name}'}, 409
    data = ip.to_dict()
    data['warnings'] = _ip_warnings(ip, subnet)
    return data, 201


@api_bp.put('/ips/<int:ip_id>', tags=[tag_ips])
@require_role('editor')
def update_ip(path: IPPath):
    ip = db.session.get(IP, path.ip_id)
    if not ip:
        return {'error': 'IP not found'}, 404
    fields = ip_fields(_json(), partial=True)
    if 'address' in fields:
        check_ip_in_subnet(fields['address'], ip.subnet)
    apply(ip, fields)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return {'error': f'{fields["address"]} is already documented in this subnet'}, 409
    data = ip.to_dict()
    data['warnings'] = _ip_warnings(ip, ip.subnet)
    return data


@api_bp.delete('/ips/<int:ip_id>', tags=[tag_ips])
@require_role('editor')
def delete_ip(path: IPPath):
    ip = db.session.get(IP, path.ip_id)
    if not ip:
        return {'error': 'IP not found'}, 404
    db.session.delete(ip)
    db.session.commit()
    return '', 204


@api_bp.post('/ips/bulk', tags=[tag_ips])
@require_role('editor')
@limiter.limit('20 per minute')
def bulk_create_ips():
    """Add up to 1000 IPs to one subnet. Valid rows are saved, invalid ones reported."""
    data = _json()
    subnet = db.session.get(Subnet, data.get('subnet_id')) if str(data.get('subnet_id', '')).isdigit() else None
    if not subnet:
        return {'error': 'Subnet not found'}, 404
    rows = data.get('ips')
    if not isinstance(rows, list) or not rows:
        return {'error': 'ips must be a non-empty list'}, 400
    if len(rows) > MAX_BULK:
        return {'error': f'At most {MAX_BULK} IPs per request'}, 400
    existing = {a for (a,) in db.session.query(IP.address).filter_by(subnet_id=subnet.id)}
    created, errors = [], []
    for row in rows:
        try:
            fields = ip_fields(row)
            check_ip_in_subnet(fields['address'], subnet)
            if fields['address'] in existing:
                raise ValidationError('already documented')
        except ValidationError as e:
            errors.append({'address': row.get('address') if isinstance(row, dict) else None,
                           'error': str(e)})
            continue
        existing.add(fields['address'])
        db.session.add(apply(IP(subnet_id=subnet.id), fields))
        created.append(fields['address'])
    db.session.commit()
    return {'created': created, 'errors': errors}, 201 if created else 400


@api_bp.get('/lookup/<address>', tags=[tag_ips])
@require_role('viewer')
def lookup(path: LookupPath):
    """Which subnet an address belongs to and whether it is documented."""
    address = normalize_ip(path.address)
    subnet = _find_subnet(address)
    ip = IP.query.filter_by(subnet_id=subnet.id, address=address).first() if subnet else None
    return {'address': address,
            'subnet': _subnet_dict(subnet) if subnet else None,
            'ip': ip.to_dict() if ip else None}


# ---------------------------------------------------------------------------
# Import / export
# ---------------------------------------------------------------------------

EXPORT_FORMAT = 3


@api_bp.get('/export', tags=[tag_data])
@require_role('viewer')
def export_data():
    subnets = Subnet.query.order_by(Subnet.id).all()
    ips = defaultdict(list)
    for ip in IP.query.order_by(IP.id):
        ips[ip.subnet_id].append({**{k: getattr(ip, k) for k in IP.FIELDS}, 'tags': [t.name for t in ip.tags]})
    out = []
    for s in subnets:
        v = s.vlan_obj
        out.append({
            'name': s.name, 'cidr': s.cidr, 'description': s.description,
            'vlan': v.vid if v else None, 'vlan_site': v.site if v else None,
            'gateway': s.gateway, 'dns_primary': s.dns_primary, 'dns_secondary': s.dns_secondary,
            'location': s.location, 'environment': s.environment,
            'tags': [t.name for t in s.tags],
            'dhcp_ranges': [{'start': r.start_address, 'end': r.end_address,
                             'description': r.description} for r in s.dhcp_ranges],
            'ips': ips[s.id],
        })
    vlans = [v.to_dict() for v in Vlan.query.order_by(Vlan.vid, Vlan.site)]
    for v in vlans:
        v.pop('id')
    response = jsonify({'format': EXPORT_FORMAT, 'version': VERSION,
                        'exported_at': datetime.utcnow().isoformat(), 'vlans': vlans, 'subnets': out})
    stamp = datetime.utcnow().strftime('%Y%m%d-%H%M')
    response.headers['Content-Disposition'] = f'attachment; filename=lattice-export-{stamp}.json'
    return response


@api_bp.post('/import', tags=[tag_data])
@require_role('admin')
@limiter.limit('5 per minute')
def import_data():
    """Import an export file. mode=merge (default) adds what's missing; mode=replace wipes first.

    The whole import is one transaction: any invalid entry aborts it and nothing changes.
    """
    data = _json()
    mode = request.args.get('mode', 'merge')
    if mode not in ('merge', 'replace'):
        return {'error': 'mode must be merge or replace'}, 400
    subnets = data.get('subnets')
    if not isinstance(subnets, list) or not subnets:
        return {'error': 'The file contains no subnets'}, 400

    if mode == 'replace':
        for model in (Discovery, IP, DhcpRange, Subnet, Vlan, Tag):
            model.query.delete()
        db.session.flush()

    # VLAN names and descriptions from format 3; numbers alone are enough otherwise
    for raw in data.get('vlans') or []:
        try:
            vid, site = int(raw['vid']), str(raw.get('site') or '')
        except (KeyError, TypeError, ValueError):
            raise ValidationError('A VLAN in the file has no valid vid')
        vlan = vlan_by_number(vid, site)
        vlan.name = str(raw.get('name') or vlan.name)[:100]
        vlan.description = raw.get('description') or vlan.description
    db.session.flush()

    added_subnets = added_ips = added_ranges = 0
    for n, raw in enumerate(subnets, 1):
        if not isinstance(raw, dict):
            raise ValidationError(f'Subnet #{n} is not an object')
        try:
            fields = subnet_fields(raw)
        except ValidationError as e:
            raise ValidationError(f'Subnet #{n} ({raw.get("name")}): {e}')
        subnet = Subnet.query.filter_by(cidr=fields['cidr']).first()
        if not subnet:
            if Subnet.query.filter_by(name=fields['name']).first():
                raise ValidationError(f'Subnet #{n}: name {fields["name"]} is already used by another CIDR')
            subnet = apply(Subnet(), fields)
            check_subnet(subnet)
            db.session.add(subnet)
            db.session.flush()
            added_subnets += 1

        for r in raw.get('dhcp_ranges') or []:
            try:
                range_fields = dhcp_range_fields(r, subnet)
            except ValidationError as e:
                if 'Overlaps' in str(e):
                    continue  # already there on merge
                raise ValidationError(f'{subnet.name}: DHCP range: {e}')
            db.session.add(DhcpRange(subnet_id=subnet.id, **range_fields))
            db.session.flush()
            db.session.refresh(subnet)
            added_ranges += 1

        existing = {a for (a,) in db.session.query(IP.address).filter_by(subnet_id=subnet.id)}
        for row in raw.get('ips') or []:
            try:
                fields = ip_fields(row)
                check_ip_in_subnet(fields['address'], subnet)
            except ValidationError as e:
                address = row.get('address') if isinstance(row, dict) else None
                raise ValidationError(f'{subnet.name}: {address}: {e}')
            if fields['address'] in existing:
                continue
            existing.add(fields['address'])
            db.session.add(apply(IP(subnet_id=subnet.id), fields))
            added_ips += 1

    db.session.commit()
    return {'subnets': added_subnets, 'ips': added_ips, 'dhcp_ranges': added_ranges}

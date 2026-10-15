"""Scans, discovered hosts and drift between the network and the documentation."""
import ipaddress
from collections import defaultdict
from datetime import datetime, timedelta

from flask import current_app, request
from flask_login import current_user
from flask_openapi3 import APIBlueprint, Tag
from pydantic import BaseModel
from sqlalchemy import and_, func, or_

from app import db, limiter
from app.auth import require_role
from app.models import IP, Discovery, Subnet
from app.scanner import SCAN_TYPES, ScanError, nmap_available, scan_jobs
from app.validation import ValidationError, normalize_mac

discovery_bp = APIBlueprint('discovery', __name__, url_prefix='/api')
tag_scan = Tag(name='Scanning', description='nmap scans and discovered hosts')
tag_drift = Tag(name='Drift', description='Differences between the network and the documentation')


class SubnetPath(BaseModel):
    subnet_id: int


class JobPath(BaseModel):
    job_id: str


class DiscoveryPath(BaseModel):
    discovery_id: int


def _short(value, length):
    return value[:length] if value else None


def record_hosts(subnet_id, hosts, source, full_sweep=False):
    """Store hosts seen on the network and refresh last_seen on documented IPs.

    `full_sweep` means every address that should answer was probed, so
    documented IPs that stayed silent may count as offline.
    """
    subnet = db.session.get(Subnet, subnet_id)
    if not subnet:
        return 0
    now = datetime.utcnow()
    documented = {ip.address: ip for ip in subnet.ips}
    known = {d.address: d for d in Discovery.query.filter_by(subnet_id=subnet_id)}
    seen = 0
    for host in hosts:
        address = host.get('address')
        if not address or not subnet.contains(address):
            continue
        address = str(ipaddress.ip_address(address))
        try:
            mac = normalize_mac(host.get('mac_address'))
        except ValidationError:
            mac = None
        record = known.get(address)
        if not record:
            record = Discovery(subnet_id=subnet_id, address=address, first_seen=now)
            db.session.add(record)
            known[address] = record
        record.last_seen = now
        record.source = source
        record.mac_address = mac or record.mac_address
        record.hostname = _short(host.get('hostname'), 255) or record.hostname
        record.vendor = _short(host.get('vendor'), 100) or record.vendor

        ip = documented.get(address)
        if ip:
            ip.last_seen = now
            if mac and not ip.mac_address:
                ip.mac_address = mac
        seen += 1
    if full_sweep:
        subnet.last_scan_at = now
    db.session.commit()
    return seen


# ---------------------------------------------------------------------------
# Scans
# ---------------------------------------------------------------------------

@discovery_bp.get('/scanner/status', tags=[tag_scan])
@require_role('viewer')
def scanner_status():
    return {'available': nmap_available(), 'scan_types': list(SCAN_TYPES)}


@discovery_bp.post('/subnets/<int:subnet_id>/scans', tags=[tag_scan])
@require_role('editor')
@limiter.limit('10 per minute')
def start_scan(path: SubnetPath):
    """Start a background nmap scan of the whole subnet."""
    if not nmap_available():
        return {'error': 'nmap is not installed on the server'}, 503
    subnet = db.session.get(Subnet, path.subnet_id)
    if not subnet:
        return {'error': 'Subnet not found'}, 404
    data = request.get_json(silent=True) or {}
    scan_type = data.get('scan_type', 'ping')
    if scan_type not in SCAN_TYPES:
        return {'error': f'scan_type must be one of: {", ".join(SCAN_TYPES)}'}, 400
    net = subnet.network
    if net.version == 6 and net.prefixlen < 112:
        return {'error': 'IPv6 subnets larger than /112 cannot be swept'}, 400
    if net.version == 4 and net.prefixlen < 16:
        return {'error': 'Subnets larger than /16 cannot be scanned in one go'}, 400
    try:
        job_id = scan_jobs.start(current_app._get_current_object(), subnet, scan_type,
                                 user=current_user.username)
    except ScanError as e:
        return {'error': str(e)}, 409
    return {'job_id': job_id}, 202


@discovery_bp.get('/scans/<job_id>', tags=[tag_scan])
@require_role('viewer')
def scan_status(path: JobPath):
    job = scan_jobs.get(path.job_id)
    if not job:
        return {'error': 'Scan not found or expired'}, 404
    if job['status'] == 'completed':
        documented = {ip.address for ip in IP.query.filter_by(subnet_id=job['subnet_id'])}
        subnet = db.session.get(Subnet, job['subnet_id'])
        if subnet and subnet.gateway:
            documented.add(subnet.gateway)
        for host in job['discovered']:
            host['documented'] = host['address'] in documented
    return job


@discovery_bp.post('/subnets/<int:subnet_id>/discoveries/import', tags=[tag_scan])
@require_role('editor')
def import_discoveries(path: SubnetPath):
    """Document discovered hosts as IPs, using what the scan learned about them."""
    subnet = db.session.get(Subnet, path.subnet_id)
    if not subnet:
        return {'error': 'Subnet not found'}, 404
    data = request.get_json(silent=True) or {}
    addresses = data.get('addresses') or []
    if not isinstance(addresses, list) or len(addresses) > 1000:
        return {'error': 'addresses must be a list of at most 1000 entries'}, 400
    wanted = set()
    for value in addresses:
        try:
            wanted.add(str(ipaddress.ip_address(str(value))))
        except ValueError:
            return {'error': f'Invalid address: {value}'}, 400
    existing = {ip.address for ip in subnet.ips}
    created = []
    for d in Discovery.query.filter(Discovery.subnet_id == subnet.id, Discovery.address.in_(wanted)):
        if d.address in existing:
            continue
        db.session.add(IP(subnet_id=subnet.id, address=d.address, status='in-use',
                          hostname=d.hostname, mac_address=d.mac_address,
                          manufacturer=d.vendor, last_seen=d.last_seen,
                          description=f'Discovered by {d.source}'))
        created.append(d.address)
    db.session.commit()
    return {'created': created, 'skipped': sorted(wanted - set(created))}, 201


# ---------------------------------------------------------------------------
# Drift
# ---------------------------------------------------------------------------

def _ip_brief(ip):
    return {'id': ip.id, 'address': ip.address, 'hostname': ip.hostname,
            'mac_address': ip.mac_address, 'subnet_id': ip.subnet_id,
            'subnet_name': ip.subnet.name, 'status': ip.status,
            'last_seen': ip.last_seen.isoformat() if ip.last_seen else None}


def drift_report(stale_days):
    cutoff = datetime.utcnow() - timedelta(days=stale_days)

    undocumented = (
        Discovery.query
        .outerjoin(IP, and_(IP.subnet_id == Discovery.subnet_id, IP.address == Discovery.address))
        .join(Subnet, Subnet.id == Discovery.subnet_id)
        # The subnet's gateway is known infrastructure, documented or not
        .filter(IP.id.is_(None), Discovery.ignored.is_(False),
                or_(Subnet.gateway.is_(None), Discovery.address != Subnet.gateway))
        .order_by(Discovery.last_seen.desc())
        .limit(1000).all()
    )

    offline = (
        IP.query.join(Subnet)
        .filter(IP.status == 'in-use', Subnet.last_scan_at.isnot(None),
                IP.created_at < Subnet.last_scan_at,
                or_(IP.last_seen.is_(None), IP.last_seen < cutoff))
        .order_by(IP.subnet_id, IP.address)
        .limit(1000).all()
    )

    conflicts = []
    dup_macs = (db.session.query(IP.mac_address).filter(IP.mac_address.isnot(None))
                .group_by(IP.mac_address).having(func.count(IP.id) > 1).limit(200).all())
    for (mac,) in dup_macs:
        ips = IP.query.filter_by(mac_address=mac).all()
        conflicts.append({'type': 'duplicate_mac', 'value': mac, 'ips': [_ip_brief(i) for i in ips]})

    host_key = func.lower(IP.hostname)
    dup_hosts = (db.session.query(host_key).filter(IP.hostname.isnot(None), IP.hostname != '')
                 .group_by(host_key).having(func.count(IP.id) > 1).limit(200).all())
    for (name,) in dup_hosts:
        ips = IP.query.filter(func.lower(IP.hostname) == name).all()
        conflicts.append({'type': 'duplicate_hostname', 'value': name, 'ips': [_ip_brief(i) for i in ips]})

    mismatches = (
        db.session.query(IP, Discovery)
        .join(Discovery, and_(Discovery.subnet_id == IP.subnet_id, Discovery.address == IP.address))
        .filter(IP.mac_address.isnot(None), Discovery.mac_address.isnot(None),
                IP.mac_address != Discovery.mac_address)
        .limit(200).all()
    )
    for ip, d in mismatches:
        conflicts.append({'type': 'mac_mismatch', 'value': ip.address,
                          'documented': ip.mac_address, 'seen': d.mac_address,
                          'ips': [_ip_brief(ip)]})

    by_subnet = defaultdict(list)
    for subnet in Subnet.query.filter(Subnet.dhcp_ranges.any()).all():
        for ip in subnet.ips:
            if ip.status in ('in-use', 'reserved') and subnet.in_dhcp_range(ip.address):
                by_subnet[subnet.id].append(ip)
    for ips in by_subnet.values():
        for ip in ips:
            conflicts.append({'type': 'static_in_pool', 'value': ip.address, 'ips': [_ip_brief(ip)]})

    return {
        'stale_days': stale_days,
        'undocumented': [d.to_dict() for d in undocumented],
        'offline': [_ip_brief(ip) for ip in offline],
        'conflicts': conflicts,
        'counts': {'undocumented': len(undocumented), 'offline': len(offline),
                   'conflicts': len(conflicts)},
    }


@discovery_bp.get('/drift', tags=[tag_drift])
@require_role('viewer')
def get_drift():
    """Undocumented hosts, documented hosts that went quiet, and conflicts."""
    return drift_report(current_app.config['STALE_DAYS'])


@discovery_bp.post('/discoveries/<int:discovery_id>/ignore', tags=[tag_drift])
@require_role('editor')
def ignore_discovery(path: DiscoveryPath):
    record = db.session.get(Discovery, path.discovery_id)
    if not record:
        return {'error': 'Not found'}, 404
    data = request.get_json(silent=True) or {}
    record.ignored = bool(data.get('ignored', True))
    db.session.commit()
    return record.to_dict()


@discovery_bp.delete('/discoveries/<int:discovery_id>', tags=[tag_drift])
@require_role('editor')
def delete_discovery(path: DiscoveryPath):
    record = db.session.get(Discovery, path.discovery_id)
    if not record:
        return {'error': 'Not found'}, 404
    db.session.delete(record)
    db.session.commit()
    return '', 204

from flask import Blueprint, jsonify, request, render_template, send_from_directory, current_app
from flask_login import login_required, current_user
from flask_openapi3 import APIBlueprint, Tag
from app import db, limiter
from app.models import Subnet, IP, ip_sort_key, Connector
from app.scanner import NetworkScanner, scan_jobs
from app.connectors.unifi import UniFiConnector
from app.security import encrypt_config, decrypt_config
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func
from sqlalchemy.orm import joinedload
import json
import ipaddress
import os
from datetime import datetime
import logging

logger = logging.getLogger(__name__)
scanner = NetworkScanner()
unifi_connector = UniFiConnector()

# Constants for pagination
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 500
MAX_SEARCH_LENGTH = 200

api_bp = APIBlueprint('api', __name__, url_prefix='/api')
main_bp = Blueprint('main', __name__)

# ============================================================================
# API Tags for Swagger Organization
# ============================================================================
tag_stats = Tag(name='Statistics', description='Dashboard statistics')
tag_subnets = Tag(name='Subnets', description='Subnet management operations')
tag_ips = Tag(name='IPs', description='IP address management')
tag_import_export = Tag(name='Import/Export', description='Data import and export')
tag_lookup = Tag(name='IP Lookup', description='IP address lookup utilities')
tag_metadata = Tag(name='Metadata', description='Metadata and enumerations')
tag_scanner = Tag(name='Network Scanner', description='Network scanning operations')
tag_connectors = Tag(name='Connectors', description='External system connectors')


# ============================================================================
# Dashboard / Statistics
# ============================================================================

@api_bp.get('/stats', tags=[tag_stats])
@login_required
def get_stats():
    """Get dashboard statistics"""
    total_subnets = Subnet.query.count()
    total_ips = IP.query.count()

    # IP status breakdown - single query
    status_counts = db.session.query(
        IP.status, func.count(IP.id)
    ).group_by(IP.status).all()
    status_breakdown = {status: count for status, count in status_counts}

    # Calculate total capacity and utilization using eager loading
    # Use joinedload to prevent N+1 queries
    subnets = Subnet.query.options(joinedload(Subnet.ips)).all()
    total_capacity = 0
    total_used = 0

    for subnet in subnets:
        # Calculate directly without calling to_dict() to avoid extra queries
        try:
            network = subnet.get_network()
            if network:
                usable = max(0, network.num_addresses - 2) if network.num_addresses > 2 else network.num_addresses
                total_capacity += usable
                total_used += len(subnet.ips)
        except Exception:
            pass

    # Environment breakdown - single query
    env_counts = db.session.query(
        Subnet.environment, func.count(Subnet.id)
    ).group_by(Subnet.environment).all()
    env_breakdown = {env or 'unassigned': count for env, count in env_counts}

    # Recent activity (last 10 IPs added/modified) with eager load of subnet
    recent_ips = IP.query.options(
        joinedload(IP.subnet)
    ).order_by(IP.updated_at.desc()).limit(10).all()

    return jsonify({
        'total_subnets': total_subnets,
        'total_ips': total_ips,
        'total_capacity': total_capacity,
        'total_used': total_used,
        'utilization': round((total_used / total_capacity * 100), 1) if total_capacity > 0 else 0,
        'status_breakdown': status_breakdown,
        'environment_breakdown': env_breakdown,
        'recent_activity': [ip.to_dict() for ip in recent_ips]
    })


# ============================================================================
# Subnet Routes
# ============================================================================

@api_bp.get('/subnets', tags=[tag_subnets])
@login_required
def get_subnets():
    """Get all subnets with optional filtering and pagination"""
    search = request.args.get('search', '').strip()[:MAX_SEARCH_LENGTH]
    environment = request.args.get('environment')
    vlan = request.args.get('vlan')
    sort_by = request.args.get('sort', 'cidr')
    sort_order = request.args.get('order', 'asc')

    # Pagination parameters
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', DEFAULT_PAGE_SIZE, type=int), MAX_PAGE_SIZE)

    # Use eager loading for IPs count
    query = Subnet.query.options(joinedload(Subnet.ips))

    if search:
        query = query.filter(
            (Subnet.name.ilike(f'%{search}%')) |
            (Subnet.cidr.ilike(f'%{search}%')) |
            (Subnet.description.ilike(f'%{search}%')) |
            (Subnet.location.ilike(f'%{search}%')) |
            (Subnet.tags.ilike(f'%{search}%'))
        )

    if environment:
        query = query.filter(Subnet.environment == environment)

    if vlan:
        try:
            query = query.filter(Subnet.vlan == int(vlan))
        except ValueError:
            pass

    # Sorting
    if sort_by == 'name':
        order_col = Subnet.name
    elif sort_by == 'vlan':
        order_col = Subnet.vlan
    elif sort_by == 'created':
        order_col = Subnet.created_at
    else:
        order_col = Subnet.cidr

    if sort_order == 'desc':
        order_col = order_col.desc()

    # Get total count for pagination metadata
    total = query.count()

    # Apply pagination
    subnets = query.order_by(order_col).offset((page - 1) * per_page).limit(per_page).all()

    # Sort by IP for CIDR (proper numeric sort)
    subnets_data = [subnet.to_dict() for subnet in subnets]
    if sort_by == 'cidr':
        subnets_data.sort(key=lambda x: ip_sort_key(x['first_ip'] or '0.0.0.0'), reverse=(sort_order == 'desc'))

    # Return with pagination metadata
    return jsonify({
        'items': subnets_data,
        'total': total,
        'page': page,
        'per_page': per_page,
        'pages': (total + per_page - 1) // per_page
    })


@api_bp.get('/subnets/<int:id>', tags=[tag_subnets])
@login_required
def get_subnet(**kwargs):
    """Get a specific subnet with its IPs"""
    id = request.view_args['id']
    subnet = Subnet.query.options(joinedload(Subnet.ips)).get_or_404(id)
    return jsonify(subnet.to_dict(include_ips=True))


@api_bp.get('/subnets/<int:id>/available-ips', tags=[tag_subnets])
@login_required
def get_available_ips(**kwargs):
    """Get available IPs in a subnet"""
    id = request.view_args['id']
    subnet = Subnet.query.options(joinedload(Subnet.ips)).get_or_404(id)
    limit = min(request.args.get('limit', 50, type=int), 200)
    return jsonify({
        'subnet_id': id,
        'available_ips': subnet.get_available_ips(limit=limit),
        'next_available': subnet.get_next_available_ip()
    })


@api_bp.post('/subnets', tags=[tag_subnets])
@login_required
@limiter.limit("30 per minute")
def create_subnet():
    """Create a new subnet"""
    try:
        data = request.json
        
        if not data.get('name') or not data.get('cidr'):
            return jsonify({'error': 'name and cidr are required'}), 400
        
        # Validate CIDR
        try:
            Subnet.validate_cidr(data['cidr'])
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
        
        # Validate gateway if provided
        if data.get('gateway'):
            try:
                Subnet.validate_ip(data['gateway'])
            except ValueError as e:
                return jsonify({'error': f'Invalid gateway: {str(e)}'}), 400
        
        # Process tags
        tags = data.get('tags', [])
        if isinstance(tags, list):
            tags = ','.join(tags)
        
        subnet = Subnet(
            name=data['name'],
            cidr=data['cidr'],
            description=data.get('description'),
            vlan=data.get('vlan'),
            gateway=data.get('gateway'),
            dns_primary=data.get('dns_primary'),
            dns_secondary=data.get('dns_secondary'),
            location=data.get('location'),
            environment=data.get('environment'),
            tags=tags
        )
        
        db.session.add(subnet)
        db.session.commit()
        
        return jsonify(subnet.to_dict()), 201
        
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Subnet name or CIDR already exists'}), 409
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400


@api_bp.put('/subnets/<int:id>', tags=[tag_subnets])
@login_required
@limiter.limit("30 per minute")
def update_subnet(**kwargs):
    """Update a subnet"""
    id = request.view_args['id']
    try:
        subnet = Subnet.query.get_or_404(id)
        data = request.json
        
        # Validate CIDR if being changed
        if data.get('cidr') and data['cidr'] != subnet.cidr:
            try:
                Subnet.validate_cidr(data['cidr'])
            except ValueError as e:
                return jsonify({'error': str(e)}), 400
        
        # Validate gateway if provided
        if data.get('gateway'):
            try:
                Subnet.validate_ip(data['gateway'])
            except ValueError as e:
                return jsonify({'error': f'Invalid gateway: {str(e)}'}), 400
        
        # Process tags
        tags = data.get('tags', subnet.tags)
        if isinstance(tags, list):
            tags = ','.join(tags)
        
        subnet.name = data.get('name', subnet.name)
        subnet.cidr = data.get('cidr', subnet.cidr)
        subnet.description = data.get('description', subnet.description)
        subnet.vlan = data.get('vlan', subnet.vlan)
        subnet.gateway = data.get('gateway', subnet.gateway)
        subnet.dns_primary = data.get('dns_primary', subnet.dns_primary)
        subnet.dns_secondary = data.get('dns_secondary', subnet.dns_secondary)
        subnet.location = data.get('location', subnet.location)
        subnet.environment = data.get('environment', subnet.environment)
        subnet.tags = tags
        
        db.session.commit()
        return jsonify(subnet.to_dict())
        
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Subnet name or CIDR already exists'}), 409
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400


@api_bp.delete('/subnets/<int:id>', tags=[tag_subnets])
@login_required
@limiter.limit("10 per minute")
def delete_subnet(**kwargs):
    """Delete a subnet and all associated IPs"""
    id = request.view_args['id']
    try:
        subnet = Subnet.query.get_or_404(id)
        db.session.delete(subnet)
        db.session.commit()
        return '', 204
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400


# ============================================================================
# IP Routes
# ============================================================================

@api_bp.get('/ips', tags=[tag_ips])
@login_required
def get_ips():
    """Get all IPs with optional filtering and pagination"""
    subnet_id = request.args.get('subnet_id')
    search = request.args.get('search', '').strip()[:MAX_SEARCH_LENGTH]
    status = request.args.get('status')
    device_type = request.args.get('device_type')

    # Pagination parameters
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', DEFAULT_PAGE_SIZE, type=int), MAX_PAGE_SIZE)

    # Eager load subnet for each IP
    query = IP.query.options(joinedload(IP.subnet))

    if subnet_id:
        try:
            query = query.filter_by(subnet_id=int(subnet_id))
        except ValueError:
            pass

    if search:
        query = query.filter(
            (IP.address.ilike(f'%{search}%')) |
            (IP.hostname.ilike(f'%{search}%')) |
            (IP.description.ilike(f'%{search}%')) |
            (IP.mac_address.ilike(f'%{search}%')) |
            (IP.owner.ilike(f'%{search}%'))
        )

    if status:
        query = query.filter_by(status=status)

    if device_type:
        query = query.filter_by(device_type=device_type)

    # Get total count
    total = query.count()

    # Apply pagination
    ips = query.offset((page - 1) * per_page).limit(per_page).all()

    # Sort IPs numerically
    ips_data = [ip.to_dict() for ip in ips]
    ips_data.sort(key=lambda x: ip_sort_key(x['address']))

    return jsonify({
        'items': ips_data,
        'total': total,
        'page': page,
        'per_page': per_page,
        'pages': (total + per_page - 1) // per_page
    })


@api_bp.get('/ips/<int:id>', tags=[tag_ips])
@login_required
def get_ip(**kwargs):
    """Get a specific IP"""
    id = request.view_args['id']
    ip = IP.query.options(joinedload(IP.subnet)).get_or_404(id)
    return jsonify(ip.to_dict())


@api_bp.post('/ips', tags=[tag_ips])
@login_required
@limiter.limit("60 per minute")
def create_ip():
    """Create a new IP entry"""
    try:
        data = request.json
        
        if not data.get('address') or not data.get('subnet_id'):
            return jsonify({'error': 'address and subnet_id are required'}), 400
        
        # Get the subnet
        subnet = Subnet.query.get(data['subnet_id'])
        if not subnet:
            return jsonify({'error': 'Subnet not found'}), 404
        
        # Validate IP address
        try:
            Subnet.validate_ip(data['address'])
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
        
        # Check if IP is within subnet range
        if not subnet.contains_ip(data['address']):
            return jsonify({'error': f'IP {data["address"]} is not within subnet {subnet.cidr}'}), 400
        
        # Check for duplicate
        existing = IP.query.filter_by(
            address=data['address'],
            subnet_id=data['subnet_id']
        ).first()
        if existing:
            return jsonify({'error': f'IP {data["address"]} already exists in this subnet'}), 409
        
        # Validate and normalize MAC address
        mac_address = None
        if data.get('mac_address'):
            try:
                mac_address = IP.validate_mac(data['mac_address'])
            except ValueError as e:
                return jsonify({'error': str(e)}), 400
        
        # Validate status
        status = data.get('status', 'available')
        if status not in IP.STATUSES:
            return jsonify({'error': f'Invalid status. Must be one of: {", ".join(IP.STATUSES)}'}), 400
        
        ip = IP(
            address=data['address'],
            hostname=data.get('hostname'),
            fqdn=data.get('fqdn'),
            description=data.get('description'),
            subnet_id=data['subnet_id'],
            status=status,
            mac_address=mac_address,
            device_type=data.get('device_type'),
            manufacturer=data.get('manufacturer'),
            model=data.get('model'),
            serial_number=data.get('serial_number'),
            owner=data.get('owner'),
            department=data.get('department'),
            notes=data.get('notes')
        )
        
        db.session.add(ip)
        db.session.commit()
        
        return jsonify(ip.to_dict()), 201
        
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'IP address already exists in this subnet'}), 409
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400


# ============================================================================
# Connectors Routes
# ============================================================================

def _safe_details(conn_type: str, config: dict) -> dict:
    """Return non-sensitive details for client display."""
    if conn_type == 'unifi':
        return {
            'base_url': config.get('base_url'),
            'site_id': config.get('site_id'),
            'auth': 'api_key' if bool(config.get('api_key')) else ('username' if bool(config.get('username')) else 'unknown'),
            'verify_ssl': bool(config.get('verify_ssl', True)),
        }
    return {}


@api_bp.get('/connectors', tags=[tag_connectors])
@login_required
def list_connectors():
    """List configured connectors from DB."""
    items = Connector.query.order_by(Connector.created_at.desc()).all()
    result = []
    for c in items:
        try:
            cfg = decrypt_config(c.config_encrypted)
        except Exception:
            cfg = {}
        result.append(c.to_dict(include_details=True, details=_safe_details(c.type, cfg)))
    return jsonify(result)


@api_bp.post('/connectors', tags=[tag_connectors])
@login_required
def create_connector():
    """Create a new connector with encrypted config."""
    data = request.get_json() or {}
    name = data.get('name')
    conn_type = data.get('type')
    config = data.get('config') or {}
    enabled = bool(data.get('enabled', True))

    if not name or not conn_type:
        return jsonify({'error': 'name and type are required'}), 400

    if conn_type == 'unifi':
        # Validate required fields
        base_url = (config.get('base_url') or '').strip()
        site_id = (config.get('site_id') or 'default').strip()
        api_key = (config.get('api_key') or '').strip()
        username = (config.get('username') or '').strip()
        password = (config.get('password') or '').strip()
        verify_ssl = bool(config.get('verify_ssl', True))
        if not base_url:
            return jsonify({'error': 'base_url is required'}), 400
        if not site_id:
            return jsonify({'error': 'site_id is required'}), 400
        if not api_key and not (username and password):
            return jsonify({'error': 'Provide api_key or username+password'}), 400
        config = {
            'base_url': base_url,
            'site_id': site_id,
            'api_key': api_key or None,
            'username': username or None,
            'password': password or None,
            'verify_ssl': verify_ssl,
        }
    else:
        return jsonify({'error': f'Unsupported connector type: {conn_type}'}), 400

    try:
        enc = encrypt_config(config)
        c = Connector(name=name, type=conn_type, config_encrypted=enc, enabled=enabled)
        db.session.add(c)
        db.session.commit()
        return jsonify(c.to_dict(include_details=True, details=_safe_details(conn_type, config))), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400


@api_bp.put('/connectors/<int:id>', tags=[tag_connectors])
@login_required
def update_connector(**kwargs):
    cid = request.view_args['id']
    c = Connector.query.get_or_404(cid)
    data = request.get_json() or {}
    name = data.get('name', c.name)
    conn_type = c.type  # immutable
    config = data.get('config') or {}
    enabled = bool(data.get('enabled', c.enabled))

    if conn_type == 'unifi':
        base_url = (config.get('base_url') or '').strip()
        site_id = (config.get('site_id') or 'default').strip()
        api_key = (config.get('api_key') or '').strip()
        username = (config.get('username') or '').strip()
        password = (config.get('password') or '').strip()
        verify_ssl = bool(config.get('verify_ssl', True))
        if not base_url:
            return jsonify({'error': 'base_url is required'}), 400
        if not site_id:
            return jsonify({'error': 'site_id is required'}), 400
        if not api_key and not (username and password):
            return jsonify({'error': 'Provide api_key or username+password'}), 400
        new_cfg = {
            'base_url': base_url,
            'site_id': site_id,
            'api_key': api_key or None,
            'username': username or None,
            'password': password or None,
            'verify_ssl': verify_ssl,
        }
    else:
        return jsonify({'error': f'Unsupported connector type: {conn_type}'}), 400

    try:
        c.name = name
        c.enabled = enabled
        c.config_encrypted = encrypt_config(new_cfg)
        db.session.commit()
        return jsonify(c.to_dict(include_details=True, details=_safe_details(conn_type, new_cfg)))
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400


@api_bp.delete('/connectors/<int:id>', tags=[tag_connectors])
@login_required
def delete_connector(**kwargs):
    cid = request.view_args['id']
    c = Connector.query.get_or_404(cid)
    try:
        db.session.delete(c)
        db.session.commit()
        return '', 204
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400


@api_bp.post('/connectors/<int:id>/test', tags=[tag_connectors])
@login_required
def test_connector(**kwargs):
    cid = request.view_args['id']
    c = Connector.query.get_or_404(cid)
    try:
        cfg = decrypt_config(c.config_encrypted)
        if c.type == 'unifi':
            connector = UniFiConnector(cfg)
            connector.connect()
            clients = connector.fetch()
            if not clients:
                return jsonify({'success': False, 'error': 'No clients returned; verify credentials or site ID'}), 400
            return jsonify({'success': True, 'connector': c.type, 'clients_sample': min(len(clients), 5)}), 200
        else:
            return jsonify({'error': f'Unsupported connector type: {c.type}'}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@api_bp.post('/connectors/<int:id>/sync', tags=[tag_connectors])
@login_required
def sync_connector(**kwargs):
    """Run sync for a specific connector by id.

    Supports dry-run via ?dry_run=true to preview adds/updates/skips without writing.
    """
    cid = request.view_args['id']
    c = Connector.query.get_or_404(cid)
    dry_run = request.args.get('dry_run', 'false').lower() == 'true'
    try:
        cfg = decrypt_config(c.config_encrypted)
        if c.type == 'unifi':
            connector = UniFiConnector(cfg)
            clients = connector.fetch()
            if not clients:
                raise RuntimeError('No clients returned; verify credentials or site ID')
        else:
            return jsonify({'error': f'Unsupported connector type: {c.type}'}), 400

        added = 0
        updated = 0
        skipped = 0
        added_items = []
        updated_items = []
        skipped_items = []

        # Preload subnets for matching
        subnets = Subnet.query.all()

        def find_subnet_for_ip(ip_str):
            for s in subnets:
                if s.contains_ip(ip_str):
                    return s
            return None

        for client in clients:
            ip_addr = client.get('ip')
            mac = client.get('mac')
            hostname = client.get('hostname')
            device_type = client.get('device_type')
            manufacturer = client.get('manufacturer')
            notes = client.get('notes')

            if not ip_addr:
                skipped += 1
                skipped_items.append({'reason': 'missing_ip', 'client': client})
                continue

            subnet = find_subnet_for_ip(ip_addr)
            if not subnet:
                skipped += 1
                skipped_items.append({'reason': 'no_matching_subnet', 'ip': ip_addr, 'client': client})
                continue

            existing = IP.query.filter_by(address=ip_addr, subnet_id=subnet.id).first()
            if existing:
                # Update known fields if empty
                delta = {}
                if mac and not existing.mac_address:
                    delta['mac_address'] = mac
                if hostname and not existing.hostname:
                    delta['hostname'] = hostname
                if manufacturer and not existing.manufacturer:
                    delta['manufacturer'] = manufacturer
                if device_type and not existing.device_type:
                    delta['device_type'] = device_type
                if notes and not existing.notes:
                    delta['notes'] = notes
                if delta:
                    if not dry_run:
                        if 'mac_address' in delta:
                            existing.mac_address = delta['mac_address']
                        if 'hostname' in delta:
                            existing.hostname = delta['hostname']
                        if 'manufacturer' in delta:
                            existing.manufacturer = delta['manufacturer']
                        if 'device_type' in delta:
                            existing.device_type = delta['device_type']
                        if 'notes' in delta:
                            existing.notes = delta['notes']
                        existing.status = 'in-use'
                    updated += 1
                    updated_items.append({
                        'ip': ip_addr,
                        'subnet': subnet.to_dict(),
                        'changes': delta
                    })
                else:
                    skipped += 1
                    skipped_items.append({'reason': 'no_changes', 'ip': ip_addr, 'subnet': subnet.to_dict()})
            else:
                if not dry_run:
                    ip = IP(
                        address=ip_addr,
                        hostname=hostname,
                        subnet_id=subnet.id,
                        status='in-use',
                        mac_address=mac,
                        device_type=device_type,
                        manufacturer=manufacturer,
                        notes=notes
                    )
                    db.session.add(ip)
                added += 1
                added_items.append({
                    'ip': ip_addr,
                    'subnet': subnet.to_dict(),
                    'hostname': hostname,
                    'mac': mac,
                    'device_type': device_type,
                    'manufacturer': manufacturer,
                    'notes': notes
                })

        if dry_run:
            return jsonify({
                'success': True,
                'dry_run': True,
                'connector': c.type,
                'connector_id': c.id,
                'clients': len(clients),
                'added': added,
                'updated': updated,
                'skipped': skipped,
                'added_items': added_items,
                'updated_items': updated_items,
                'skipped_items': skipped_items,
            }), 200

        c.last_sync_at = datetime.utcnow()
        db.session.commit()

        return jsonify({
            'success': True,
            'connector': c.type,
            'connector_id': c.id,
            'clients': len(clients),
            'added': added,
            'updated': updated,
            'skipped': skipped,
            'last_sync_at': c.last_sync_at.isoformat() if c.last_sync_at else None,
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Connector sync failed: {str(e)}'}), 500


@api_bp.put('/ips/<int:id>', tags=[tag_ips])
@login_required
@limiter.limit("60 per minute")
def update_ip(**kwargs):
    """Update an IP entry"""
    id = request.view_args['id']
    try:
        ip = IP.query.get_or_404(id)
        data = request.json
        
        # Validate new IP address if changing
        if data.get('address') and data['address'] != ip.address:
            try:
                Subnet.validate_ip(data['address'])
            except ValueError as e:
                return jsonify({'error': str(e)}), 400
            
            # Check if new IP is within subnet
            if not ip.subnet.contains_ip(data['address']):
                return jsonify({'error': f'IP {data["address"]} is not within subnet {ip.subnet.cidr}'}), 400
            
            # Check for duplicate
            existing = IP.query.filter_by(
                address=data['address'],
                subnet_id=ip.subnet_id
            ).first()
            if existing and existing.id != id:
                return jsonify({'error': f'IP {data["address"]} already exists in this subnet'}), 409
        
        # Validate and normalize MAC address
        if 'mac_address' in data:
            if data['mac_address']:
                try:
                    data['mac_address'] = IP.validate_mac(data['mac_address'])
                except ValueError as e:
                    return jsonify({'error': str(e)}), 400
        
        # Validate status
        if data.get('status') and data['status'] not in IP.STATUSES:
            return jsonify({'error': f'Invalid status. Must be one of: {", ".join(IP.STATUSES)}'}), 400
        
        ip.address = data.get('address', ip.address)
        ip.hostname = data.get('hostname', ip.hostname)
        ip.fqdn = data.get('fqdn', ip.fqdn)
        ip.description = data.get('description', ip.description)
        ip.status = data.get('status', ip.status)
        ip.mac_address = data.get('mac_address', ip.mac_address)
        ip.device_type = data.get('device_type', ip.device_type)
        ip.manufacturer = data.get('manufacturer', ip.manufacturer)
        ip.model = data.get('model', ip.model)
        ip.serial_number = data.get('serial_number', ip.serial_number)
        ip.owner = data.get('owner', ip.owner)
        ip.department = data.get('department', ip.department)
        ip.notes = data.get('notes', ip.notes)
        
        db.session.commit()
        return jsonify(ip.to_dict())
        
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'IP address already exists in this subnet'}), 409
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400


@api_bp.delete('/ips/<int:id>', tags=[tag_ips])
@login_required
@limiter.limit("30 per minute")
def delete_ip(**kwargs):
    """Delete an IP entry"""
    id = request.view_args['id']
    try:
        ip = IP.query.get_or_404(id)
        db.session.delete(ip)
        db.session.commit()
        return '', 204
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400


# ============================================================================
# Bulk Operations
# ============================================================================

@api_bp.post('/ips/bulk', tags=[tag_ips])
@login_required
@limiter.limit("10 per minute")
def bulk_create_ips():
    """Create multiple IPs at once"""
    try:
        data = request.json
        
        if not data.get('subnet_id'):
            return jsonify({'error': 'subnet_id is required'}), 400
        
        subnet = Subnet.query.get(data['subnet_id'])
        if not subnet:
            return jsonify({'error': 'Subnet not found'}), 404
        
        ips_data = data.get('ips', [])
        if not ips_data:
            return jsonify({'error': 'No IPs provided'}), 400
        
        created = []
        errors = []
        
        for ip_data in ips_data:
            try:
                address = ip_data.get('address')
                if not address:
                    errors.append({'address': None, 'error': 'Address is required'})
                    continue
                
                # Validate IP
                try:
                    Subnet.validate_ip(address)
                except ValueError as e:
                    errors.append({'address': address, 'error': str(e)})
                    continue
                
                # Check range
                if not subnet.contains_ip(address):
                    errors.append({'address': address, 'error': f'Not within subnet {subnet.cidr}'})
                    continue
                
                # Check duplicate
                existing = IP.query.filter_by(address=address, subnet_id=subnet.id).first()
                if existing:
                    errors.append({'address': address, 'error': 'Already exists'})
                    continue
                
                ip = IP(
                    address=address,
                    hostname=ip_data.get('hostname'),
                    description=ip_data.get('description'),
                    subnet_id=subnet.id,
                    status=ip_data.get('status', 'available'),
                    device_type=ip_data.get('device_type'),
                    owner=ip_data.get('owner')
                )
                db.session.add(ip)
                created.append(address)
                
            except Exception as e:
                errors.append({'address': ip_data.get('address'), 'error': str(e)})
        
        db.session.commit()
        
        return jsonify({
            'created': len(created),
            'errors': len(errors),
            'created_ips': created,
            'error_details': errors
        }), 201 if created else 400
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400


# ============================================================================
# Export / Import
# ============================================================================

@api_bp.get('/export', tags=[tag_import_export])
@login_required
def export_data():
    """Export all data as JSON"""
    subnets = Subnet.query.all()
    
    export_data = {
        'version': '1.0',
        'exported_at': datetime.utcnow().isoformat(),
        'subnets': [subnet.to_dict(include_ips=True) for subnet in subnets]
    }
    
    return jsonify(export_data)


@api_bp.post('/import', tags=[tag_import_export])
@login_required
@limiter.limit("5 per minute")
def import_data():
    """Import data from JSON"""
    try:
        data = request.json
        
        if not data.get('subnets'):
            return jsonify({'error': 'No subnets found in import data'}), 400
        
        mode = request.args.get('mode', 'merge')  # merge or replace
        
        if mode == 'replace':
            # Delete all existing data
            IP.query.delete()
            Subnet.query.delete()
            db.session.commit()
        
        imported_subnets = 0
        imported_ips = 0
        errors = []
        
        for subnet_data in data['subnets']:
            try:
                # Check if subnet exists (by CIDR)
                existing = Subnet.query.filter_by(cidr=subnet_data['cidr']).first()
                
                if existing and mode == 'merge':
                    subnet = existing
                else:
                    tags = subnet_data.get('tags', [])
                    if isinstance(tags, list):
                        tags = ','.join(tags)
                    
                    subnet = Subnet(
                        name=subnet_data['name'],
                        cidr=subnet_data['cidr'],
                        description=subnet_data.get('description'),
                        vlan=subnet_data.get('vlan'),
                        gateway=subnet_data.get('gateway'),
                        dns_primary=subnet_data.get('dns_primary'),
                        dns_secondary=subnet_data.get('dns_secondary'),
                        location=subnet_data.get('location'),
                        environment=subnet_data.get('environment'),
                        tags=tags
                    )
                    db.session.add(subnet)
                    db.session.flush()
                    imported_subnets += 1
                
                # Import IPs
                for ip_data in subnet_data.get('ips', []):
                    existing_ip = IP.query.filter_by(
                        address=ip_data['address'],
                        subnet_id=subnet.id
                    ).first()
                    
                    if existing_ip:
                        continue
                    
                    ip = IP(
                        address=ip_data['address'],
                        hostname=ip_data.get('hostname'),
                        fqdn=ip_data.get('fqdn'),
                        description=ip_data.get('description'),
                        subnet_id=subnet.id,
                        status=ip_data.get('status', 'available'),
                        mac_address=ip_data.get('mac_address'),
                        device_type=ip_data.get('device_type'),
                        manufacturer=ip_data.get('manufacturer'),
                        model=ip_data.get('model'),
                        serial_number=ip_data.get('serial_number'),
                        owner=ip_data.get('owner'),
                        department=ip_data.get('department'),
                        notes=ip_data.get('notes')
                    )
                    db.session.add(ip)
                    imported_ips += 1
                    
            except Exception as e:
                errors.append({'subnet': subnet_data.get('name'), 'error': str(e)})
        
        db.session.commit()
        
        return jsonify({
            'imported_subnets': imported_subnets,
            'imported_ips': imported_ips,
            'errors': errors
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400


# ============================================================================
# Lookup Endpoints
# ============================================================================

@api_bp.get('/lookup/ip/<ip_address>', tags=[tag_lookup])
@login_required
def lookup_ip(**kwargs):
    """Find which subnet an IP belongs to"""
    ip_address = request.view_args['ip_address']
    try:
        ip_obj = ipaddress.ip_address(ip_address)
    except ValueError:
        return jsonify({'error': 'Invalid IP address'}), 400

    subnets = Subnet.query.all()

    for subnet in subnets:
        if subnet.contains_ip(ip_address):
            # Check if IP is registered
            ip = IP.query.filter_by(address=ip_address, subnet_id=subnet.id).first()
            return jsonify({
                'ip': ip_address,
                'subnet': subnet.to_dict(),
                'registered': ip.to_dict() if ip else None
            })

    return jsonify({
        'ip': ip_address,
        'subnet': None,
        'registered': None,
        'message': 'IP not found in any managed subnet'
    })


@api_bp.get('/environments', tags=[tag_metadata])
@login_required
def get_environments():
    """Get list of all environments"""
    envs = db.session.query(Subnet.environment).distinct().all()
    return jsonify([env[0] for env in envs if env[0]])


@api_bp.get('/device-types', tags=[tag_metadata])
@login_required
def get_device_types():
    """Get list of all device types"""
    types = db.session.query(IP.device_type).distinct().all()
    return jsonify([t[0] for t in types if t[0]])


# ============================================================================
# Frontend Routes
# ============================================================================

@main_bp.route('/')
def index():
    return render_template('index.html')


# Fallback static routes (ensure JS/CSS load even if proxied differently)
@main_bp.route('/js/<path:filename>')
def serve_js(filename):
    return send_from_directory(os.path.join(current_app.static_folder, 'js'), filename)


@main_bp.route('/css/<path:filename>')
def serve_css(filename):
    return send_from_directory(os.path.join(current_app.static_folder, 'css'), filename)


# ============================================================================
# Network Scanning Routes
# ============================================================================

@api_bp.get('/scanner/status', tags=[tag_scanner])
@login_required
def scanner_status():
    """Check if network scanner is available"""
    return jsonify({
        'available': scanner.is_available(),
        'message': 'Nmap is available' if scanner.is_available() else 'Nmap is not installed or not in PATH'
    })


@api_bp.post('/scanner/scan-subnet/<int:subnet_id>', tags=[tag_scanner])
@login_required
@limiter.limit("5 per minute")
def scan_subnet(**kwargs):
    """Scan a subnet for live hosts"""
    subnet_id = request.view_args['subnet_id']
    if not scanner.is_available():
        return jsonify({'error': 'Nmap scanner not available'}), 503
    
    subnet = Subnet.query.get(subnet_id)
    if not subnet:
        return jsonify({'error': 'Subnet not found'}), 404
    
    data = request.get_json()
    scan_type = data.get('scan_type', 'ping')
    
    try:
        logger.info(f"Starting {scan_type} scan for subnet {subnet.name} ({subnet.cidr})")
        
        # Perform scan
        scan_result = scanner.scan_subnet(subnet.cidr, scan_type)
        
        if 'error' in scan_result:
            return jsonify(scan_result), 400
        
        # Get recommendations
        recommendations = scanner.recommend_ips_for_subnet(
            subnet_id,
            scan_result['discovered']
        )
        
        return jsonify({
            'subnet_id': subnet_id,
            'subnet_name': subnet.name,
            'subnet_cidr': subnet.cidr,
            'scan_result': scan_result,
            'recommendations': recommendations,
            'timestamp': datetime.utcnow().isoformat()
        })
    
    except Exception as e:
        logger.error(f"Scan error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@api_bp.post('/scanner/scan-subnet/<int:subnet_id>/start', tags=[tag_scanner])
@login_required
@limiter.limit("5 per minute")
def scan_subnet_start(**kwargs):
    """Start an asynchronous subnet scan and return a job id"""
    subnet_id = request.view_args['subnet_id']
    if not scanner.is_available():
        return jsonify({'error': 'Nmap scanner not available'}), 503

    subnet = Subnet.query.get(subnet_id)
    if not subnet:
        return jsonify({'error': 'Subnet not found'}), 404

    data = request.get_json() or {}
    scan_type = data.get('scan_type', 'ping')

    try:
        job_id = scan_jobs.start_scan(subnet.cidr, scan_type)
        return jsonify({
            'job_id': job_id,
            'subnet_id': subnet_id,
            'subnet_name': subnet.name,
            'subnet_cidr': subnet.cidr,
            'scan_type': scan_type
        }), 202
    except Exception as e:
        logger.error(f"Failed to start async scan: {str(e)}")
        return jsonify({'error': str(e)}), 500


@api_bp.get('/scanner/scan-jobs/<string:job_id>', tags=[tag_scanner])
@login_required
def scan_job_status(**kwargs):
    """Get the current status, logs, and partial results for a scan job"""
    job_id = request.view_args['job_id']
    job = scan_jobs.get_job(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404

    return jsonify({
        'id': job['id'],
        'status': job['status'],
        'subnet': job['subnet'],
        'scan_type': job['scan_type'],
        'logs': job['logs'],
        'discovered': job['discovered'],
        'started_at': job['started_at'],
        'finished_at': job['finished_at'],
        'total_discovered': job['total_discovered'],
        'error': job['error']
    })


@api_bp.post('/scanner/bulk-import', tags=[tag_scanner])
@login_required
@limiter.limit("10 per minute")
def bulk_import_ips():
    """
    Bulk import recommended IPs from scan results
    
    POST data:
    {
        'subnet_id': int,
        'ips': [
            {
                'address': '192.168.1.10',
                'hostname': 'server1',
                'mac_address': '00:11:22:33:44:55',
                'device_type': 'Server',
                'status': 'in-use'
            }
        ],
        'auto_enrich': true (default: true)
    }
    """
    data = request.get_json()
    subnet_id = data.get('subnet_id')
    ips = data.get('ips', [])
    auto_enrich = data.get('auto_enrich', True)
    
    subnet = Subnet.query.get(subnet_id)
    if not subnet:
        return jsonify({'error': 'Subnet not found'}), 404
    
    imported = []
    failed = []
    
    for ip_data in ips:
        try:
            # Validate IP is in subnet
            if not subnet.contains_ip(ip_data['address']):
                failed.append({
                    'address': ip_data['address'],
                    'error': 'IP not in subnet CIDR range'
                })
                continue
            
            # Check if already exists
            existing = IP.query.filter_by(
                address=ip_data['address'],
                subnet_id=subnet_id
            ).first()
            
            if existing:
                failed.append({
                    'address': ip_data['address'],
                    'error': 'IP already in inventory'
                })
                continue
            
            # Create new IP entry
            new_ip = IP(
                address=ip_data['address'],
                subnet_id=subnet_id,
                status=ip_data.get('status', 'in-use'),
                hostname=ip_data.get('hostname') if auto_enrich else None,
                mac_address=ip_data.get('mac_address') if auto_enrich else None,
                device_type=ip_data.get('device_type') if auto_enrich else None,
                description=f"Discovered via network scan - {ip_data.get('os_info', 'Unknown device')}" if auto_enrich else None
            )
            
            db.session.add(new_ip)
            imported.append(ip_data['address'])
        
        except Exception as e:
            failed.append({
                'address': ip_data.get('address', 'unknown'),
                'error': str(e)
            })
    
    db.session.commit()
    
    return jsonify({
        'subnet_id': subnet_id,
        'imported_count': len(imported),
        'failed_count': len(failed),
        'imported': imported,
        'failed': failed,
        'timestamp': datetime.utcnow().isoformat()
    }), 201


@api_bp.post('/scanner/verify/<int:subnet_id>', tags=[tag_scanner])
@login_required
@limiter.limit("5 per minute")
def verify_subnet(**kwargs):
    """Verify status of all IPs in a subnet"""
    subnet_id = request.view_args['subnet_id']
    if not scanner.is_available():
        return jsonify({'error': 'Nmap scanner not available'}), 503
    
    subnet = Subnet.query.get(subnet_id)
    if not subnet:
        return jsonify({'error': 'Subnet not found'}), 404
    
    try:
        results = []
        live_count = 0
        
        for ip_obj in subnet.ips:
            result = scanner.verify_ip_status(ip_obj.address, subnet_id)
            results.append(result)
            
            if result.get('is_live'):
                live_count += 1
        
        return jsonify({
            'subnet_id': subnet_id,
            'subnet_name': subnet.name,
            'total_ips': len(subnet.ips),
            'live_ips': live_count,
            'results': results,
            'timestamp': datetime.utcnow().isoformat()
        })
    
    except Exception as e:
        logger.error(f"Verification error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@api_bp.post('/scanner/verify-ip', tags=[tag_scanner])
@login_required
@limiter.limit("30 per minute")
def verify_ip():
    """
    Verify status of a single IP
    
    POST data:
    {
        'address': '192.168.1.10',
        'subnet_id': 1
    }
    """
    if not scanner.is_available():
        return jsonify({'error': 'Nmap scanner not available'}), 503
    
    data = request.get_json()
    address = data.get('address')
    subnet_id = data.get('subnet_id')
    
    if not address or not subnet_id:
        return jsonify({'error': 'address and subnet_id are required'}), 400
    
    try:
        result = scanner.verify_ip_status(address, subnet_id)
        return jsonify(result)
    
    except Exception as e:
        logger.error(f"IP verification error: {str(e)}")
        return jsonify({'error': str(e)}), 500

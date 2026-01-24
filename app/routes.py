from flask import Blueprint, jsonify, request, render_template
from app import db
from app.models import Subnet, IP, ip_sort_key
from app.scanner import NetworkScanner
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func
import json
import ipaddress
from datetime import datetime
import logging

logger = logging.getLogger(__name__)
scanner = NetworkScanner()

api_bp = Blueprint('api', __name__, url_prefix='/api')
main_bp = Blueprint('main', __name__)


# ============================================================================
# Dashboard / Statistics
# ============================================================================

@api_bp.route('/stats', methods=['GET'])
def get_stats():
    """Get dashboard statistics"""
    total_subnets = Subnet.query.count()
    total_ips = IP.query.count()
    
    # IP status breakdown
    status_counts = db.session.query(
        IP.status, func.count(IP.id)
    ).group_by(IP.status).all()
    status_breakdown = {status: count for status, count in status_counts}
    
    # Calculate total capacity and utilization
    subnets = Subnet.query.all()
    total_capacity = 0
    total_used = 0
    
    for subnet in subnets:
        data = subnet.to_dict()
        total_capacity += data['usable_ips']
        total_used += data['used_ips']
    
    # Environment breakdown
    env_counts = db.session.query(
        Subnet.environment, func.count(Subnet.id)
    ).group_by(Subnet.environment).all()
    env_breakdown = {env or 'unassigned': count for env, count in env_counts}
    
    # Recent activity (last 10 IPs added/modified)
    recent_ips = IP.query.order_by(IP.updated_at.desc()).limit(10).all()
    
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

@api_bp.route('/subnets', methods=['GET'])
def get_subnets():
    """Get all subnets with optional filtering"""
    search = request.args.get('search', '')
    environment = request.args.get('environment')
    vlan = request.args.get('vlan')
    sort_by = request.args.get('sort', 'cidr')
    sort_order = request.args.get('order', 'asc')
    
    query = Subnet.query
    
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
        query = query.filter(Subnet.vlan == int(vlan))
    
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
    
    subnets = query.order_by(order_col).all()
    
    # Sort by IP for CIDR (proper numeric sort)
    if sort_by == 'cidr':
        subnets_data = [subnet.to_dict() for subnet in subnets]
        subnets_data.sort(key=lambda x: ip_sort_key(x['first_ip'] or '0.0.0.0'), reverse=(sort_order == 'desc'))
        return jsonify(subnets_data)
    
    return jsonify([subnet.to_dict() for subnet in subnets])


@api_bp.route('/subnets/<int:id>', methods=['GET'])
def get_subnet(id):
    """Get a specific subnet with its IPs"""
    subnet = Subnet.query.get_or_404(id)
    return jsonify(subnet.to_dict(include_ips=True))


@api_bp.route('/subnets/<int:id>/available-ips', methods=['GET'])
def get_available_ips(id):
    """Get available IPs in a subnet"""
    subnet = Subnet.query.get_or_404(id)
    limit = request.args.get('limit', 50, type=int)
    return jsonify({
        'subnet_id': id,
        'available_ips': subnet.get_available_ips(limit=limit),
        'next_available': subnet.get_next_available_ip()
    })


@api_bp.route('/subnets', methods=['POST'])
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


@api_bp.route('/subnets/<int:id>', methods=['PUT'])
def update_subnet(id):
    """Update a subnet"""
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


@api_bp.route('/subnets/<int:id>', methods=['DELETE'])
def delete_subnet(id):
    """Delete a subnet and all associated IPs"""
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

@api_bp.route('/ips', methods=['GET'])
def get_ips():
    """Get all IPs with optional filtering"""
    subnet_id = request.args.get('subnet_id')
    search = request.args.get('search', '')
    status = request.args.get('status')
    device_type = request.args.get('device_type')
    
    query = IP.query
    
    if subnet_id:
        query = query.filter_by(subnet_id=subnet_id)
    
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
    
    ips = query.all()
    
    # Sort IPs numerically
    ips_data = [ip.to_dict() for ip in ips]
    ips_data.sort(key=lambda x: ip_sort_key(x['address']))
    
    return jsonify(ips_data)


@api_bp.route('/ips/<int:id>', methods=['GET'])
def get_ip(id):
    """Get a specific IP"""
    ip = IP.query.get_or_404(id)
    return jsonify(ip.to_dict())


@api_bp.route('/ips', methods=['POST'])
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


@api_bp.route('/ips/<int:id>', methods=['PUT'])
def update_ip(id):
    """Update an IP entry"""
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


@api_bp.route('/ips/<int:id>', methods=['DELETE'])
def delete_ip(id):
    """Delete an IP entry"""
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

@api_bp.route('/ips/bulk', methods=['POST'])
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

@api_bp.route('/export', methods=['GET'])
def export_data():
    """Export all data as JSON"""
    subnets = Subnet.query.all()
    
    export_data = {
        'version': '1.0',
        'exported_at': datetime.utcnow().isoformat(),
        'subnets': [subnet.to_dict(include_ips=True) for subnet in subnets]
    }
    
    return jsonify(export_data)


@api_bp.route('/import', methods=['POST'])
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

@api_bp.route('/lookup/ip/<ip_address>', methods=['GET'])
def lookup_ip(ip_address):
    """Find which subnet an IP belongs to"""
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


@api_bp.route('/environments', methods=['GET'])
def get_environments():
    """Get list of all environments"""
    envs = db.session.query(Subnet.environment).distinct().all()
    return jsonify([env[0] for env in envs if env[0]])


@api_bp.route('/device-types', methods=['GET'])
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


# ============================================================================
# Network Scanning Routes
# ============================================================================

@api_bp.route('/scanner/status', methods=['GET'])
def scanner_status():
    """Check if network scanner is available"""
    return jsonify({
        'available': scanner.is_available(),
        'message': 'Nmap is available' if scanner.is_available() else 'Nmap is not installed or not in PATH'
    })


@api_bp.route('/scanner/scan-subnet/<int:subnet_id>', methods=['POST'])
def scan_subnet(subnet_id):
    """
    Scan a subnet for live hosts
    
    POST data:
    {
        'scan_type': 'ping' or 'full' (default: 'ping')
    }
    """
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


@api_bp.route('/scanner/bulk-import', methods=['POST'])
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


@api_bp.route('/scanner/verify/<int:subnet_id>', methods=['POST'])
def verify_subnet(subnet_id):
    """
    Verify status of all IPs in a subnet
    
    Returns verification results for each IP
    """
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


@api_bp.route('/scanner/verify-ip', methods=['POST'])
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

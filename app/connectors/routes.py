"""Connector management and sync. Admin only: connectors hold credentials."""
import ipaddress
import logging
from collections import defaultdict
from datetime import datetime

from flask import request
from flask_openapi3 import APIBlueprint, Tag
from pydantic import BaseModel

from app import db, limiter
from app.auth import require_role
from app.connectors import CONNECTOR_TYPES
from app.connectors.base import ConnectorError
from app.models import IP, Connector, Subnet
from app.security import decrypt_config, encrypt_config
from app.validation import ValidationError, normalize_mac

logger = logging.getLogger(__name__)

connectors_bp = APIBlueprint('connectors', __name__, url_prefix='/api/connectors')
tag = Tag(name='Connectors', description='Pull hosts from other systems')

# Fields a sync may fill in on an existing IP, if they are empty
SYNC_FIELDS = (('mac', 'mac_address'), ('hostname', 'hostname'),
               ('vendor', 'manufacturer'), ('device_type', 'device_type'))


class ConnectorPath(BaseModel):
    connector_id: int


def _config(connector):
    try:
        return decrypt_config(connector.config_encrypted)
    except Exception:
        logger.warning('Could not decrypt connector %s; was SECRET_KEY or CONNECTOR_SECRET changed?',
                       connector.id)
        return None


def _dict(connector, config=None):
    config = config if config is not None else _config(connector)
    cls = CONNECTOR_TYPES.get(connector.type)
    details = cls.public_details(config) if cls and config else {}
    data = connector.to_dict(details)
    data['credentials_ok'] = config is not None
    return data


def _get(connector_id):
    connector = db.session.get(Connector, connector_id)
    if not connector:
        return None, ({'error': 'Connector not found'}, 404)
    return connector, None


@connectors_bp.get('', tags=[tag])
@require_role('admin')
def list_connectors():
    items = Connector.query.order_by(Connector.created_at.desc()).all()
    return {'items': [_dict(c) for c in items], 'types': list(CONNECTOR_TYPES)}


@connectors_bp.post('', tags=[tag])
@require_role('admin')
def create_connector():
    data = request.get_json(silent=True) or {}
    cls = CONNECTOR_TYPES.get(data.get('type'))
    if not cls:
        return {'error': f'type must be one of: {", ".join(CONNECTOR_TYPES)}'}, 400
    name = (data.get('name') or '').strip()[:100]
    if not name:
        return {'error': 'name is required'}, 400
    config = cls.clean_config(data.get('config') or {})
    connector = Connector(name=name, type=cls.type, enabled=bool(data.get('enabled', True)),
                          config_encrypted=encrypt_config(config))
    db.session.add(connector)
    db.session.commit()
    return _dict(connector, config), 201


@connectors_bp.put('/<int:connector_id>', tags=[tag])
@require_role('admin')
def update_connector(path: ConnectorPath):
    connector, err = _get(path.connector_id)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    if 'name' in data:
        name = (data.get('name') or '').strip()[:100]
        if not name:
            return {'error': 'name is required'}, 400
        connector.name = name
    if 'enabled' in data:
        connector.enabled = bool(data['enabled'])
    config = _config(connector)
    if 'config' in data:
        config = CONNECTOR_TYPES[connector.type].clean_config(data['config'] or {}, config or {})
        connector.config_encrypted = encrypt_config(config)
    db.session.commit()
    return _dict(connector, config)


@connectors_bp.delete('/<int:connector_id>', tags=[tag])
@require_role('admin')
def delete_connector(path: ConnectorPath):
    connector, err = _get(path.connector_id)
    if err:
        return err
    db.session.delete(connector)
    db.session.commit()
    return '', 204


def _fetch(connector):
    config = _config(connector)
    if config is None:
        raise ConnectorError('Stored credentials cannot be decrypted. Edit the connector and enter them again.')
    return CONNECTOR_TYPES[connector.type](config).fetch()


@connectors_bp.post('/<int:connector_id>/test', tags=[tag])
@require_role('admin')
@limiter.limit('10 per minute')
def test_connector(path: ConnectorPath):
    connector, err = _get(path.connector_id)
    if err:
        return err
    try:
        hosts = _fetch(connector)
    except ConnectorError as e:
        return {'ok': False, 'error': str(e)}, 502
    return {'ok': True, 'hosts': len(hosts)}


def plan_sync(hosts):
    """Work out what a sync would change, without touching the database."""
    subnets = sorted(Subnet.query.all(), key=lambda s: s.network.prefixlen, reverse=True)
    existing = {(ip.subnet_id, ip.address): ip for ip in IP.query.all()}
    plan = {'add': [], 'update': [], 'skip': [], 'seen': defaultdict(list)}
    planned = set()
    for host in hosts:
        try:
            address = str(ipaddress.ip_address(str(host.get('ip') or '')))
        except ValueError:
            plan['skip'].append({'ip': host.get('ip'), 'hostname': host.get('hostname'),
                                 'reason': 'no IP address'})
            continue
        subnet = next((s for s in subnets if s.contains(address)), None)
        if not subnet:
            plan['skip'].append({'ip': address, 'hostname': host.get('hostname'),
                                 'reason': 'not in any subnet'})
            continue
        try:
            mac = normalize_mac(host.get('mac'))
        except ValidationError:
            mac = None
        values = {'mac': mac, 'hostname': (host.get('hostname') or '')[:255] or None,
                  'vendor': (host.get('vendor') or '')[:100] or None,
                  'device_type': host.get('device_type')}
        plan['seen'][subnet.id].append({'address': address, 'mac_address': mac,
                                        'hostname': values['hostname'], 'vendor': values['vendor']})
        key = (subnet.id, address)
        if key in planned:
            continue
        planned.add(key)
        ip = existing.get(key)
        if ip:
            changes = {field: values[src] for src, field in SYNC_FIELDS
                       if values[src] and not getattr(ip, field)}
            if changes:
                plan['update'].append({'id': ip.id, 'ip': address, 'subnet': subnet.name,
                                       'subnet_id': subnet.id, 'changes': changes})
            else:
                plan['skip'].append({'ip': address, 'hostname': values['hostname'],
                                     'reason': 'already up to date'})
        else:
            plan['add'].append({'ip': address, 'subnet': subnet.name, 'subnet_id': subnet.id,
                                'hostname': values['hostname'], 'mac_address': mac,
                                'manufacturer': values['vendor'],
                                'device_type': values['device_type']})
    return plan


@connectors_bp.post('/<int:connector_id>/sync', tags=[tag])
@require_role('admin')
@limiter.limit('10 per minute')
def sync_connector(path: ConnectorPath):
    """Sync hosts into Lattice. ?dry_run=true returns the plan without saving.

    New hosts are added as in-use; existing IPs only get empty fields filled in.
    """
    from app.discovery import record_hosts
    connector, err = _get(path.connector_id)
    if err:
        return err
    try:
        hosts = _fetch(connector)
    except ConnectorError as e:
        return {'error': str(e)}, 502
    plan = plan_sync(hosts)
    summary = {'hosts': len(hosts), 'add': plan['add'], 'update': plan['update'],
               'skip': plan['skip']}
    if request.args.get('dry_run', '').lower() in ('1', 'true'):
        return {**summary, 'dry_run': True}

    for item in plan['add']:
        db.session.add(IP(subnet_id=item['subnet_id'], address=item['ip'], status='in-use',
                          hostname=item['hostname'], mac_address=item['mac_address'],
                          manufacturer=item['manufacturer'], device_type=item['device_type'],
                          description=f'Added by {connector.name}'))
    for item in plan['update']:
        ip = db.session.get(IP, item['id'])
        for field, value in item['changes'].items():
            setattr(ip, field, value)
    connector.last_sync_at = datetime.utcnow()
    db.session.commit()
    for subnet_id, seen in plan['seen'].items():
        record_hosts(subnet_id, seen, source=connector.type)
    return {**summary, 'dry_run': False, 'last_sync_at': connector.last_sync_at.isoformat()}

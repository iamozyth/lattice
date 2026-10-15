"""VLANs and tags: shared labels that subnets and addresses point to."""
from flask import request
from flask_openapi3 import APIBlueprint, Tag as ApiTag
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app import db, history
from app.auth import require_role
from app.models import IP, USED_STATUSES, Tag, Vlan, ip_tags, subnet_tags
from app.validation import ValidationError

catalog_bp = APIBlueprint('catalog', __name__, url_prefix='/api')
tag_api = ApiTag(name='VLANs and tags')

history.track(Vlan, 'vlan', lambda v: f'VLAN {v.vid} · {v.name}', lambda v: None)
history.track(Tag, 'tag', lambda t: t.name, lambda t: None)


class VlanPath(BaseModel):
    vlan_id: int


class TagPath(BaseModel):
    tag_id: int


def resolve_tags(names):
    """Tag rows for the names, matched case-insensitively; new names are created."""
    if not names:
        return []
    existing = {t.name.lower(): t for t in Tag.query.filter(func.lower(Tag.name).in_([n.lower() for n in names]))}
    out = []
    for name in names:
        tag = existing.get(name.lower())
        if not tag:
            tag = Tag(name=name)
            db.session.add(tag)
            existing[name.lower()] = tag
        out.append(tag)
    return out


def vlan_by_number(vid, site=''):
    """The VLAN with this number (and site), created as "VLAN n" if missing."""
    vlan = Vlan.query.filter_by(vid=vid, site=site).first()
    if not vlan:
        vlan = Vlan(vid=vid, name=f'VLAN {vid}', site=site)
        db.session.add(vlan)
    return vlan


def _vlan_fields(data, partial=False):
    out = {}
    if not partial or 'vid' in data:
        try:
            vid = int(data.get('vid'))
        except (TypeError, ValueError):
            raise ValidationError('VLAN ID must be a number')
        if not 1 <= vid <= 4094:
            raise ValidationError('VLAN ID must be between 1 and 4094')
        out['vid'] = vid
    if not partial or 'name' in data:
        name = str(data.get('name') or '').strip()[:100]
        if not name:
            raise ValidationError('name is required')
        out['name'] = name
    if 'site' in data:
        out['site'] = str(data.get('site') or '').strip()[:100]
    if 'description' in data:
        out['description'] = str(data.get('description') or '').strip()[:2000] or None
    return out


def _vlan_dict(vlan, counts):
    data = vlan.to_dict()
    data['subnets'] = []
    for s in sorted(vlan.subnets, key=lambda x: (x.network.version, int(x.network.network_address))):
        total, used = counts.get(s.id, (0, 0))
        usable = s.usable_count
        data['subnets'].append({'id': s.id, 'name': s.name, 'cidr': s.cidr, 'used_ips': used,
                                'utilization': round(used / usable * 100, 1) if usable else 0})
    return data


def _counts():
    q = db.session.query(IP.subnet_id, func.count(IP.id), func.count(IP.id).filter(IP.status.in_(USED_STATUSES)))
    return {sid: (total, used) for sid, total, used in q.group_by(IP.subnet_id)}


@catalog_bp.get('/vlans', tags=[tag_api])
@require_role('viewer')
def list_vlans():
    counts = _counts()
    vlans = Vlan.query.order_by(Vlan.vid, Vlan.site).all()
    return {'items': [_vlan_dict(v, counts) for v in vlans]}


@catalog_bp.post('/vlans', tags=[tag_api])
@require_role('editor')
def create_vlan():
    vlan = Vlan(**_vlan_fields(request.get_json(silent=True) or {}))
    db.session.add(vlan)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return {'error': 'That VLAN ID already exists at this site'}, 409
    return _vlan_dict(vlan, {}), 201


@catalog_bp.put('/vlans/<int:vlan_id>', tags=[tag_api])
@require_role('editor')
def update_vlan(path: VlanPath):
    vlan = db.session.get(Vlan, path.vlan_id)
    if not vlan:
        return {'error': 'VLAN not found'}, 404
    for key, value in _vlan_fields(request.get_json(silent=True) or {}, partial=True).items():
        setattr(vlan, key, value)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return {'error': 'That VLAN ID already exists at this site'}, 409
    return _vlan_dict(vlan, _counts())


@catalog_bp.delete('/vlans/<int:vlan_id>', tags=[tag_api])
@require_role('editor')
def delete_vlan(path: VlanPath):
    vlan = db.session.get(Vlan, path.vlan_id)
    if not vlan:
        return {'error': 'VLAN not found'}, 404
    for s in vlan.subnets:  # unlink in the session so history sees it
        s.vlan_id = None
    db.session.delete(vlan)
    db.session.commit()
    return '', 204


@catalog_bp.get('/tags', tags=[tag_api])
@require_role('viewer')
def list_tags():
    subnet_n = dict(db.session.query(subnet_tags.c.tag_id, func.count()).group_by(subnet_tags.c.tag_id).all())
    ip_n = dict(db.session.query(ip_tags.c.tag_id, func.count()).group_by(ip_tags.c.tag_id).all())
    tags = Tag.query.order_by(func.lower(Tag.name)).all()
    return {'items': [{'id': t.id, 'name': t.name, 'subnets': subnet_n.get(t.id, 0), 'ips': ip_n.get(t.id, 0)}
                      for t in tags]}


@catalog_bp.put('/tags/<int:tag_id>', tags=[tag_api])
@require_role('editor')
def rename_tag(path: TagPath):
    """Rename a tag. Renaming onto an existing tag merges the two."""
    tag = db.session.get(Tag, path.tag_id)
    if not tag:
        return {'error': 'Tag not found'}, 404
    name = str((request.get_json(silent=True) or {}).get('name') or '').strip()[:50]
    if not name:
        return {'error': 'name is required'}, 400
    other = Tag.query.filter(func.lower(Tag.name) == name.lower(), Tag.id != tag.id).first()
    if other:
        for obj in list(tag.subnets) + list(tag.ips):
            if other not in obj.tags:
                obj.tags.append(other)
            obj.tags.remove(tag)
        db.session.delete(tag)
        tag = other
    else:
        tag.name = name
    db.session.commit()
    return {'id': tag.id, 'name': tag.name}


@catalog_bp.delete('/tags/<int:tag_id>', tags=[tag_api])
@require_role('editor')
def delete_tag(path: TagPath):
    tag = db.session.get(Tag, path.tag_id)
    if not tag:
        return {'error': 'Tag not found'}, 404
    db.session.delete(tag)
    db.session.commit()
    return '', 204


def tag_filter(query, model, name):
    """Restrict a Subnet or IP query to rows carrying the tag."""
    return query.filter(model.tags.any(func.lower(Tag.name) == name.lower()))


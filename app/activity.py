"""Read access to the change history."""
from flask import request
from flask_openapi3 import APIBlueprint, Tag

from app.auth import require_role
from app.models import Change

activity_bp = APIBlueprint('activity', __name__, url_prefix='/api')
tag = Tag(name='Activity', description='Who changed what, and when')


def _int(name):
    value = request.args.get(name, '')
    return int(value) if value.isdigit() else None


@activity_bp.get('/changes', tags=[tag])
@require_role('viewer')
def list_changes():
    """Newest first. Filters: entity, id, subnet_id, user, q. Page with before=<id>."""
    query = Change.query
    if request.args.get('entity'):
        query = query.filter(Change.entity == request.args['entity'])
    if _int('id') is not None:
        query = query.filter(Change.entity_id == _int('id'))
    if _int('subnet_id') is not None:
        query = query.filter(Change.subnet_id == _int('subnet_id'))
    if request.args.get('user'):
        query = query.filter(Change.username == request.args['user'])
    q = request.args.get('q', '').strip()[:100]
    if q:
        escaped = q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        query = query.filter(Change.label.ilike(f'%{escaped}%', escape='\\'))
    if _int('before') is not None:
        query = query.filter(Change.id < _int('before'))
    limit = min(max(_int('limit') or 50, 1), 200)
    items = query.order_by(Change.id.desc()).limit(limit + 1).all()
    more = len(items) > limit
    items = items[:limit]
    return {'items': [c.to_dict() for c in items], 'next': items[-1].id if more else None}

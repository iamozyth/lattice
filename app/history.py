"""Change history: every create, update and delete of the objects people manage.

One SQLAlchemy listener covers every write path (UI, API, imports, scans,
connector syncs), so nothing can forget to log. Changes are collected before
the flush and written right after it, when new rows have their IDs.
"""
import json
import logging
from datetime import date, datetime, timedelta

from flask import has_request_context, session
from flask_login import current_user
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app import db
from app.models import IP, Change, Connector, DhcpRange, Setting, Subnet, User

logger = logging.getLogger(__name__)

# Fields that change on their own and would drown out real edits
IGNORED = {'id', 'last_seen', 'updated_at', 'created_at', 'last_scan_at', 'last_sync_at', 'session_version'}
# Fields whose values must never be stored
SECRET = {'password_hash', 'config_encrypted'}

TRACKED = {
    Subnet: ('subnet', lambda o: f'{o.name} ({o.cidr})', lambda o: o.id),
    IP: ('ip', lambda o: o.address, lambda o: o.subnet_id),
    DhcpRange: ('dhcp_range', lambda o: f'{o.start_address} – {o.end_address}', lambda o: o.subnet_id),
    User: ('user', lambda o: o.username, lambda o: None),
    Connector: ('connector', lambda o: o.name, lambda o: None),
    Setting: ('setting', lambda o: o.key, lambda o: None),
}


def track(model, entity, label, subnet_of):
    """Register another model (VLANs and tags add themselves)."""
    TRACKED[model] = (entity, label, subnet_of)


def _value(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray, memoryview)):
        return '(changed)'
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return str(v)


def _setting_diff(old, new):
    """Settings hold JSON: report the keys that changed, never secrets."""
    try:
        a, b = json.loads(old or '{}'), json.loads(new or '{}')
    except ValueError:
        return {'value': '(changed)'}
    out = {}
    for key in sorted(set(a) | set(b)):
        if a.get(key) != b.get(key):
            out[key] = '(changed)' if 'secret' in key else [a.get(key), b.get(key)]
    return out


def _columns(obj):
    return [c.key for c in inspect(obj).mapper.column_attrs if c.key not in IGNORED]


def _diff(obj, action):
    state = inspect(obj)
    if isinstance(obj, Setting):
        hist = state.attrs.value.history
        old = hist.deleted[0] if hist.deleted else (None if action == 'create' else obj.value)
        new = None if action == 'delete' else obj.value
        return _setting_diff(old, new)
    out = {}
    for key in _columns(obj):
        if action == 'update':
            hist = state.attrs[key].history
            if not hist.has_changes():
                continue
            old = hist.deleted[0] if hist.deleted else None
            new = hist.added[0] if hist.added else None
            if old == new:
                continue
        else:
            value = getattr(obj, key)
            if value in (None, '', False) and key not in SECRET:
                continue
            old, new = (None, value) if action == 'create' else (value, None)
        out[key] = '(changed)' if key in SECRET else [_value(old), _value(new)]
    for key, rel in state.mapper.relationships.items():
        if key in getattr(obj, 'TRACKED_RELATIONS', ()):
            hist = state.attrs[key].history
            if action == 'update' and hist.has_changes():
                before = sorted({str(x) for x in list(hist.deleted) + list(hist.unchanged)})
                after = sorted({str(x) for x in list(hist.added) + list(hist.unchanged)})
                if before != after:
                    out[key] = [before, after]
            elif action == 'create' and getattr(obj, key):
                out[key] = [None, sorted(str(x) for x in getattr(obj, key))]
    return out


def _actor():
    if has_request_context() and current_user and current_user.is_authenticated:
        return current_user.id, current_user.username, session.get('via', 'session')
    return None, 'system', 'system'


@event.listens_for(Session, 'before_flush')
def _collect(sess, flush_context, instances):
    pending = sess.info.setdefault('history', [])
    for action, objs in (('create', sess.new), ('update', sess.dirty), ('delete', sess.deleted)):
        for obj in objs:
            meta = TRACKED.get(type(obj))
            if not meta:
                continue
            if action == 'update' and not sess.is_modified(obj, include_collections=True):
                continue
            diff = _diff(obj, action)
            if action == 'update' and not diff:
                continue  # only ignored fields changed, e.g. last_seen
            pending.append((obj, action, diff, meta))


@event.listens_for(Session, 'after_flush')
def _write(sess, flush_context):
    pending = sess.info.pop('history', [])
    if not pending:
        return
    user_id, username, via = _actor()
    now = datetime.utcnow()
    rows = []
    for obj, action, diff, (entity, label, subnet_of) in pending:
        try:
            rows.append({'at': now, 'user_id': user_id, 'username': username, 'via': via, 'action': action,
                         'entity': entity, 'entity_id': obj.id if hasattr(obj, 'id') else None,
                         'label': str(label(obj))[:255], 'subnet_id': subnet_of(obj), 'diff': diff})
        except Exception:  # never let history break a write
            logger.exception('history: could not record %s %s', action, entity)
    if rows:
        sess.connection().execute(Change.__table__.insert(), rows)


@event.listens_for(Session, 'after_rollback')
def _forget(sess):
    sess.info.pop('history', None)


def purge(days):
    """Drop entries older than `days`. Returns how many went."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    n = Change.query.filter(Change.at < cutoff).delete()
    db.session.commit()
    return n

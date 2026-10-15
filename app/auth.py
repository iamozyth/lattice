"""Authentication, roles and user management."""
from functools import wraps

from flask import request, session
from flask_login import current_user, login_required, login_user, logout_user
from flask_openapi3 import APIBlueprint, Tag
from pydantic import BaseModel
from sqlalchemy import func, text

from app import VERSION, db, limiter
from app.models import ROLES, User

auth_bp = APIBlueprint('auth', __name__, url_prefix='/api/auth')
tag = Tag(name='Auth', description='Login, account and users')

# Serialises setup and admin changes so two requests can't race past a check
SETUP_LOCK = 7_431_001


class UserPath(BaseModel):
    user_id: int


def require_role(role):
    """Allow the request only for logged-in users with at least `role`."""
    def decorator(f):
        @wraps(f)
        @login_required
        def wrapper(*args, **kwargs):
            if not current_user.has_role(role):
                return {'error': f'{role.capitalize()} role required'}, 403
            return f(*args, **kwargs)
        return wrapper
    return decorator


def _json():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _clean(value, max_len):
    value = (value or '').strip() if isinstance(value, str) else ''
    return value[:max_len]


def _valid_email(email):
    return 3 <= len(email) <= 120 and '@' in email and ' ' not in email


def _lock():
    db.session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': SETUP_LOCK})


def _active_admins():
    return User.query.filter_by(role='admin', is_active=True).count()


@auth_bp.get('/status', tags=[tag])
def status():
    """Whether setup is needed and who is logged in."""
    return {
        'needs_setup': db.session.query(func.count(User.id)).scalar() == 0,
        'user': current_user.to_dict() if current_user.is_authenticated else None,
        'via': session.get('via', 'local') if current_user.is_authenticated else None,
        'version': VERSION,
    }


@auth_bp.post('/setup', tags=[tag])
@limiter.limit('5 per minute')
def setup():
    """Create the first admin. Only works while there are no users."""
    data = _json()
    username = _clean(data.get('username'), 80)
    email = _clean(data.get('email'), 120)
    password = data.get('password') or ''
    if len(username) < 3:
        return {'error': 'Username must be at least 3 characters'}, 400
    if not _valid_email(email):
        return {'error': 'Enter a valid email address'}, 400
    _lock()
    if User.query.count() > 0:
        db.session.rollback()
        return {'error': 'Setup has already been completed'}, 403
    user = User(username=username, email=email, role='admin', is_active=True)
    try:
        user.set_password(password)
    except ValueError as e:
        db.session.rollback()
        return {'error': str(e)}, 400
    db.session.add(user)
    db.session.commit()
    login_user(user, remember=True)
    return {'user': user.to_dict()}, 201


@auth_bp.post('/login', tags=[tag])
@limiter.limit('10 per minute')
def login():
    from app.sso import local_login_allowed, settings
    if not local_login_allowed():
        return {'error': f"Sign in with {settings()['name']}"}, 403
    data = _json()
    user = User.query.filter_by(username=_clean(data.get('username'), 80)).first()
    if not user or not user.check_password(data.get('password') or ''):
        return {'error': 'Invalid username or password'}, 401
    if not user.is_active:
        return {'error': 'This account is disabled'}, 403
    login_user(user, remember=bool(data.get('remember', True)))
    return {'user': user.to_dict()}


@auth_bp.post('/logout', tags=[tag])
def logout():
    from app.sso import logout_redirect
    to = logout_redirect()  # also end the provider session after an SSO sign-in
    session.clear()
    logout_user()  # after clear(): it marks the remember-me cookie for deletion
    return {'ok': True, 'redirect': to}


@auth_bp.post('/password', tags=[tag])
@login_required
@limiter.limit('10 per minute')
def change_password():
    """Change your password. Signs out every other session."""
    data = _json()
    if not current_user.check_password(data.get('current_password') or ''):
        return {'error': 'Current password is incorrect'}, 400
    try:
        current_user.set_password(data.get('new_password') or '')
    except ValueError as e:
        return {'error': str(e)}, 400
    current_user.session_version += 1
    db.session.commit()
    login_user(current_user, remember=True)
    return {'ok': True}


# ---------------------------------------------------------------------------
# Users (admin)
# ---------------------------------------------------------------------------

@auth_bp.get('/users', tags=[tag])
@require_role('admin')
def list_users():
    return {'items': [u.to_dict() for u in User.query.order_by(User.username).all()]}


@auth_bp.post('/users', tags=[tag])
@require_role('admin')
def create_user():
    data = _json()
    username = _clean(data.get('username'), 80)
    email = _clean(data.get('email'), 120)
    role = data.get('role') or 'viewer'
    if len(username) < 3:
        return {'error': 'Username must be at least 3 characters'}, 400
    if not _valid_email(email):
        return {'error': 'Enter a valid email address'}, 400
    if role not in ROLES:
        return {'error': f'role must be one of: {", ".join(ROLES)}'}, 400
    if User.query.filter((User.username == username) | (User.email == email)).first():
        return {'error': 'Username or email is already taken'}, 409
    user = User(username=username, email=email, role=role, is_active=True)
    try:
        user.set_password(data.get('password') or '')
    except ValueError as e:
        return {'error': str(e)}, 400
    db.session.add(user)
    db.session.commit()
    return {'user': user.to_dict()}, 201


@auth_bp.put('/users/<int:user_id>', tags=[tag])
@require_role('admin')
def update_user(path: UserPath):
    data = _json()
    _lock()
    user = db.session.get(User, path.user_id)
    if not user:
        db.session.rollback()
        return {'error': 'User not found'}, 404
    is_self = user.id == current_user.id
    revoke = False

    if 'email' in data:
        email = _clean(data['email'], 120)
        if not _valid_email(email):
            return {'error': 'Enter a valid email address'}, 400
        if User.query.filter(User.email == email, User.id != user.id).first():
            return {'error': 'Email is already taken'}, 409
        user.email = email
    if 'role' in data and data['role'] != user.role:
        if data['role'] not in ROLES:
            return {'error': f'role must be one of: {", ".join(ROLES)}'}, 400
        if is_self:
            return {'error': 'You cannot change your own role'}, 400
        if user.role == 'admin' and user.is_active and _active_admins() <= 1:
            return {'error': 'Lattice needs at least one active admin'}, 400
        user.role = data['role']
        revoke = True
    if 'is_active' in data and bool(data['is_active']) != user.is_active:
        if is_self:
            return {'error': 'You cannot disable your own account'}, 400
        if not data['is_active'] and user.role == 'admin' and _active_admins() <= 1:
            return {'error': 'Lattice needs at least one active admin'}, 400
        user.is_active = bool(data['is_active'])
        revoke = True
    if data.get('password'):
        try:
            user.set_password(data['password'])
        except ValueError as e:
            return {'error': str(e)}, 400
        revoke = True

    if revoke and not is_self:
        user.session_version += 1
    db.session.commit()
    return {'user': user.to_dict()}


@auth_bp.delete('/users/<int:user_id>', tags=[tag])
@require_role('admin')
def delete_user(path: UserPath):
    if path.user_id == current_user.id:
        return {'error': 'You cannot delete your own account'}, 400
    _lock()
    user = db.session.get(User, path.user_id)
    if not user:
        db.session.rollback()
        return {'error': 'User not found'}, 404
    if user.role == 'admin' and user.is_active and _active_admins() <= 1:
        return {'error': 'Lattice needs at least one active admin'}, 400
    db.session.delete(user)
    db.session.commit()
    return '', 204


@auth_bp.get('/updates', tags=[tag])
@require_role('admin')
def check_updates():
    """Compare the running version with the latest GitHub release."""
    from app.updates import check_for_updates
    return check_for_updates(VERSION)

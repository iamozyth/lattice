"""Single sign-on with OpenID Connect (authentik, Keycloak, Pocket ID, ...).

Authorization code flow with PKCE. ID tokens are verified against the
provider's published keys (RS256, PS256, ES256); unsigned or HMAC tokens are
refused. Roles come from the person's groups at every sign-in.

Settings are saved from Settings -> Single sign-on, or set with OIDC_* and
LOCAL_LOGIN environment variables, which win field by field.
"""
import base64
import hashlib
import json
import logging
import os
import re
import secrets
import time
from urllib.parse import urlencode, urlparse

import jwt
import requests
from flask import Blueprint, current_app, jsonify, redirect, request, session
from flask_login import current_user, login_user
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app import db, limiter
from app.auth import auth_bp, require_role
from app.models import ROLES, Setting, User
from app.security import decrypt_config, encrypt_config

logger = logging.getLogger(__name__)

sso_bp = Blueprint('sso', __name__)

STATE_COOKIE = 'lattice_oidc'
STATE_TTL = 600
ALGORITHMS = ['RS256', 'PS256', 'ES256']
TIMEOUT = 10
DEFAULTS = {
    'enabled': False,
    'issuer': '',
    'client_id': '',
    'name': 'SSO',
    'scopes': 'openid profile email',
    'groups_claim': 'groups',
    'groups': {'admin': ['lattice-admins'], 'editor': ['lattice-editors'], 'viewer': ['lattice-viewers']},
    'session_hours': 12,
    'local_login': True,
}
ENV = {
    'issuer': 'OIDC_ISSUER', 'client_id': 'OIDC_CLIENT_ID', 'name': 'OIDC_NAME',
    'scopes': 'OIDC_SCOPES', 'groups_claim': 'OIDC_GROUPS_CLAIM', 'session_hours': 'OIDC_SESSION_HOURS',
    'local_login': 'LOCAL_LOGIN',
}
ENV_GROUPS = {'admin': 'OIDC_ADMIN_GROUPS', 'editor': 'OIDC_EDITOR_GROUPS', 'viewer': 'OIDC_VIEWER_GROUPS'}


class SsoError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _list(value):
    items = value if isinstance(value, list) else str(value or '').split(',')
    return [str(x).strip() for x in items if str(x).strip()][:20]


def _env(name):
    value = os.environ.get(name)
    return value if value not in (None, '') else None


def _env_secret():
    if _env('OIDC_CLIENT_SECRET'):
        return os.environ['OIDC_CLIENT_SECRET'].strip()
    path = _env('OIDC_CLIENT_SECRET_FILE')
    if path:
        with open(path) as fh:
            return fh.read().strip()
    return None


def _allow_http(url):
    host = urlparse(url).hostname or ''
    return host in ('localhost', '127.0.0.1', '::1') or current_app.config.get('OIDC_ALLOW_HTTP')


def check_url(url, what):
    parsed = urlparse(url or '')
    if parsed.scheme == 'https' or (parsed.scheme == 'http' and _allow_http(url)):
        if parsed.hostname:
            return url
    raise SsoError('config', f'{what} must be an https:// URL: {url}')


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def _saved():
    row = db.session.get(Setting, 'sso')
    if not row:
        return {}
    data = json.loads(row.value)
    if data.get('client_secret_enc'):
        try:
            data['client_secret'] = decrypt_config(data.pop('client_secret_enc').encode())['secret']
        except Exception:
            logger.warning('sso: saved client secret cannot be decrypted (SECRET_KEY or CONNECTOR_SECRET changed?)')
            data.pop('client_secret_enc', None)
    return data


def locked():
    """Fields set in the environment; shown read-only in the UI."""
    out = {k: _env(v) is not None for k, v in ENV.items()}
    out.update({f'groups.{r}': _env(v) is not None for r, v in ENV_GROUPS.items()})
    out['client_secret'] = bool(_env('OIDC_CLIENT_SECRET') or _env('OIDC_CLIENT_SECRET_FILE'))
    return out


def settings(saved=None):
    """What applies: environment first, then saved settings, then defaults."""
    saved = _saved() if saved is None else saved
    s = {**DEFAULTS, **saved, 'groups': {**DEFAULTS['groups'], **saved.get('groups', {})}}
    s.setdefault('client_secret', '')
    for key, var in ENV.items():
        if _env(var) is not None:
            s[key] = _env(var)
    if _env('LOCAL_LOGIN') is not None:
        s['local_login'] = _env('LOCAL_LOGIN').lower() not in ('0', 'off', 'false', 'no')
    if _env('OIDC_SESSION_HOURS') is not None:
        s['session_hours'] = float(_env('OIDC_SESSION_HOURS'))
    for role, var in ENV_GROUPS.items():
        if _env(var) is not None:
            s['groups'][role] = _list(_env(var))
    secret = _env_secret()
    if secret:
        s['client_secret'] = secret
    if _env('OIDC_ISSUER'):
        s['enabled'] = True  # configured on the server: on
    if not s['enabled']:
        s['local_login'] = True  # never lock everyone out
    return s


def public_url():
    base = _env('PUBLIC_URL') or request.url_root
    return base.rstrip('/')


def redirect_uri():
    return f'{public_url()}/auth/oidc/callback'


def validate(data):
    """Next saved settings from form input; raises SsoError('input', ...)."""
    def bad(msg):
        return SsoError('input', msg)
    cur = _saved()
    n = {**DEFAULTS, **cur, 'groups': {**DEFAULTS['groups'], **cur.get('groups', {})}}
    if 'enabled' in data:
        n['enabled'] = bool(data['enabled'])
    if 'issuer' in data:
        issuer = str(data['issuer'] or '').strip()
        if issuer and not re.match(r'^https?://[^\s?#]+$', issuer):
            raise bad('Issuer must be a URL, e.g. https://auth.example.com/application/o/lattice/')
        n['issuer'] = issuer
    if 'client_id' in data:
        n['client_id'] = str(data['client_id'] or '').strip()[:200]
    if data.get('client_secret'):
        n['client_secret'] = str(data['client_secret']).strip()[:500]  # empty keeps the saved one
    if 'name' in data:
        n['name'] = str(data['name'] or '').strip()[:40] or 'SSO'
    if isinstance(data.get('groups'), dict):
        for role in ROLES:
            if role in data['groups']:
                n['groups'][role] = _list(data['groups'][role])
    if 'session_hours' in data:
        try:
            hours = float(data['session_hours'])
        except (TypeError, ValueError):
            raise bad('Session length must be a number of hours')
        if not 1 <= hours <= 168:
            raise bad('Session length must be between 1 and 168 hours')
        n['session_hours'] = hours
    if 'local_login' in data:
        n['local_login'] = bool(data['local_login'])
    if n['enabled']:
        eff = settings(n)
        if not eff['issuer']:
            raise bad('Enter the issuer URL from your provider')
        check_url(eff['issuer'], 'Issuer')
        if not eff['client_id']:
            raise bad('Enter the client ID')
        if not eff['client_secret']:
            raise bad('Enter the client secret')
        if not any(eff['groups'].values()):
            raise bad('Name at least one group, or nobody can sign in')
    else:
        n['local_login'] = True
    return n


def save(n):
    data = {k: v for k, v in n.items() if k != 'client_secret'}
    if n.get('client_secret'):
        data['client_secret_enc'] = encrypt_config({'secret': n['client_secret']}).decode()
    row = db.session.get(Setting, 'sso') or Setting(key='sso')
    row.value = json.dumps(data)
    db.session.add(row)
    db.session.commit()
    _clients.clear()


def view():
    s = settings()
    out = {k: v for k, v in s.items() if k != 'client_secret'}
    out.update(has_secret=bool(s['client_secret']), locked=locked(), redirect_uri=redirect_uri(),
               active=active() is not None)
    return out


# ---------------------------------------------------------------------------
# OpenID Connect client
# ---------------------------------------------------------------------------

class Oidc:
    def __init__(self, s):
        self.issuer = check_url(s['issuer'], 'Issuer')
        self.client_id = s['client_id']
        self.client_secret = s['client_secret']
        self.scopes = s['scopes']
        self.groups_claim = s['groups_claim']
        self._meta = None
        self._meta_at = 0
        self._jwks = None

    def _get_json(self, url, **kw):
        try:
            resp = requests.request(kw.pop('method', 'GET'), url, timeout=TIMEOUT, allow_redirects=False,
                                    headers={'Accept': 'application/json', **kw.pop('headers', {})}, **kw)
        except requests.RequestException as e:
            raise SsoError('provider', f'{urlparse(url).netloc}: {type(e).__name__}: {e}')
        if 300 <= resp.status_code < 400:
            raise SsoError('provider', f'{urlparse(url).path} redirects; use the exact issuer URL from the provider')
        try:
            body = resp.json()
        except ValueError:
            raise SsoError('provider', f'{urlparse(url).path}: not JSON (HTTP {resp.status_code})')
        if not resp.ok:
            detail = body.get('error_description') or body.get('error') or ''
            raise SsoError('provider', f'{urlparse(url).path}: HTTP {resp.status_code} {detail}'.strip())
        return body

    def discover(self):
        if self._meta and time.time() - self._meta_at < 3600:
            return self._meta
        meta = self._get_json(f"{self.issuer.rstrip('/')}/.well-known/openid-configuration")
        if meta.get('issuer', '').rstrip('/') != self.issuer.rstrip('/'):
            raise SsoError('config', f"The provider calls itself {meta.get('issuer')}, not {self.issuer}")
        for key in ('authorization_endpoint', 'token_endpoint', 'jwks_uri'):
            if not meta.get(key):
                raise SsoError('config', f"The provider's discovery document has no {key}")
            check_url(meta[key], key)
        self._meta, self._meta_at = meta, time.time()
        self._jwks = jwt.PyJWKClient(meta['jwks_uri'], cache_keys=True, lifespan=3600, timeout=TIMEOUT)
        return meta

    def begin(self, redirect_to):
        meta = self.discover()
        state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        url = meta['authorization_endpoint'] + '?' + urlencode({
            'response_type': 'code', 'client_id': self.client_id, 'redirect_uri': redirect_to,
            'scope': self.scopes, 'state': state, 'nonce': nonce,
            'code_challenge': challenge, 'code_challenge_method': 'S256',
        })
        return url, {'state': state, 'nonce': nonce, 'verifier': verifier}

    def finish(self, code, flow, redirect_to):
        meta = self.discover()
        tokens = self._get_json(meta['token_endpoint'], method='POST', auth=(self.client_id, self.client_secret), data={
            'grant_type': 'authorization_code', 'code': code, 'redirect_uri': redirect_to,
            'code_verifier': flow['verifier']})
        id_token = tokens.get('id_token')
        if not id_token:
            raise SsoError('provider', 'The provider returned no ID token (is the openid scope allowed?)')
        try:
            header = jwt.get_unverified_header(id_token)
            if header.get('alg') not in ALGORITHMS:
                raise SsoError('token', f"ID token algorithm {header.get('alg')} is not accepted; "
                                        'set a signing key on the provider (RS256 or ES256)')
            key = self._jwks.get_signing_key_from_jwt(id_token).key
            claims = jwt.decode(id_token, key, algorithms=ALGORITHMS, audience=self.client_id,
                                issuer=meta['issuer'], leeway=60,
                                options={'require': ['exp', 'iat', 'sub', 'aud', 'iss']})
        except jwt.PyJWTError as e:
            raise SsoError('token', f'ID token rejected: {e}')
        if claims.get('nonce') != flow['nonce']:
            raise SsoError('token', 'ID token nonce does not match')
        aud = claims['aud'] if isinstance(claims['aud'], list) else [claims['aud']]
        if len(aud) > 1 and claims.get('azp') != self.client_id:
            raise SsoError('token', 'ID token azp is not this client')
        if self.groups_claim not in claims and meta.get('userinfo_endpoint') and tokens.get('access_token'):
            info = self._get_json(meta['userinfo_endpoint'], headers={'Authorization': f"Bearer {tokens['access_token']}"})
            if info.get('sub') != claims['sub']:
                raise SsoError('token', 'userinfo is for another subject')
            for k in (self.groups_claim, 'preferred_username', 'name', 'email'):
                claims.setdefault(k, info.get(k))
        groups = claims.get(self.groups_claim) or []
        groups = [str(g) for g in (groups if isinstance(groups, list) else [groups])]
        return claims, groups, id_token

    def logout_url(self, id_token, after):
        try:
            meta = self.discover()
        except SsoError:
            return None
        end = meta.get('end_session_endpoint')
        if not end:
            return None
        return end + '?' + urlencode({'id_token_hint': id_token, 'client_id': self.client_id,
                                      'post_logout_redirect_uri': after})


_clients = {}


def active():
    """The OIDC client for the current settings, or None when SSO is off."""
    s = settings()
    if not s['enabled'] or not (s['issuer'] and s['client_id'] and s['client_secret']):
        return None
    key = (s['issuer'], s['client_id'], s['client_secret'], s['scopes'], s['groups_claim'])
    if key not in _clients:
        try:
            _clients.clear()
            _clients[key] = Oidc(s)
        except SsoError as e:
            logger.warning('sso: off, %s', e)
            return None
    return _clients[key]


def role_for(groups, mapping):
    have = set(groups)
    for role in ('admin', 'editor', 'viewer'):
        if have & set(mapping.get(role) or []):
            return role
    return None


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

def _free_username(base):
    base = re.sub(r'[^A-Za-z0-9._-]', '-', base or 'user').strip('-.')[:70] or 'user'
    name, n = base, 2
    while User.query.filter_by(username=name).first():
        name, n = f'{base}-{n}', n + 1
    return name


def provision(claims, role):
    """Find or create the account tied to the provider's user ID."""
    user = User.query.filter_by(sso_subject=claims['sub']).first()
    email = (claims.get('email') or '').strip()[:120]
    if user:
        if not user.is_active:
            return None
        if user.role != role:
            user.role = role
            user.session_version += 1  # sessions with the old role end
        if email and email != user.email and not User.query.filter_by(email=email).first():
            user.email = email
    else:
        username = _free_username(claims.get('preferred_username') or email.split('@')[0] or claims.get('name'))
        if not email or User.query.filter_by(email=email).first():
            email = f"{username}@sso.invalid"
        user = User(username=username, email=email, role=role, is_active=True, sso_subject=claims['sub'],
                    password_hash='!sso')  # no password: check_password never matches
        db.session.add(user)
    db.session.commit()
    return user


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def _serializer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='lattice-oidc')


_used_states = {}


def _to_login(error):
    resp = redirect(f'/login?error={error}')
    resp.delete_cookie(STATE_COOKIE, path='/auth/oidc')
    return resp


@sso_bp.route('/auth/oidc/start')
@limiter.limit('20 per minute')
def start():
    client = active()
    if not client:
        return _to_login('sso_off')
    try:
        url, flow = client.begin(redirect_uri())
    except SsoError as e:
        logger.warning("sso: can't start sign-in: %s", e)
        return _to_login('sso_unavailable')
    resp = redirect(url)
    resp.set_cookie(STATE_COOKIE, _serializer().dumps(flow), max_age=STATE_TTL, path='/auth/oidc',
                    httponly=True, samesite='Lax', secure=request.is_secure)
    return resp


@sso_bp.route('/auth/oidc/callback')
@limiter.limit('20 per minute')
def callback():
    client = active()
    if not client:
        return _to_login('sso_off')
    try:
        flow = _serializer().loads(request.cookies.get(STATE_COOKIE, ''), max_age=STATE_TTL)
    except (BadSignature, SignatureExpired):
        return _to_login('sso_state')
    state = request.args.get('state', '')
    if not secrets.compare_digest(state, flow.get('state', '')) or state in _used_states:
        return _to_login('sso_state')
    now = time.time()
    for st in [k for k, at in _used_states.items() if now - at > STATE_TTL]:
        del _used_states[st]
    _used_states[state] = now
    if request.args.get('error'):
        logger.info('sso: provider refused: %s', request.args.get('error')[:100])
        return _to_login('sso_failed')
    try:
        claims, groups, id_token = client.finish(request.args.get('code', ''), flow, redirect_uri())
    except SsoError as e:
        logger.warning('sso: sign-in failed from %s: %s', request.remote_addr, e)
        return _to_login('sso_unavailable' if e.code == 'provider' and 'HTTP' not in str(e) else 'sso_failed')

    s = settings()
    label = claims.get('preferred_username') or claims.get('email') or claims['sub']
    role = role_for(groups, s['groups'])
    if not role:
        logger.info('sso: %s has none of the lattice groups (has: %s)', json.dumps(str(label)), json.dumps(groups))
        return _to_login('sso_denied')
    user = provision(claims, role)
    if not user:
        logger.info('sso: %s is disabled in lattice', json.dumps(str(label)))
        return _to_login('sso_denied')

    session.clear()
    login_user(user, remember=False)
    session.permanent = True
    session['via'] = 'sso'
    session['sso_until'] = now + float(s['session_hours']) * 3600
    session['id_token'] = id_token
    logger.info('auth: %s signed in with %s as %s', user.username, s['name'], role)
    resp = redirect('/')
    resp.delete_cookie(STATE_COOKIE, path='/auth/oidc')
    return resp


@auth_bp.get('/config')
def auth_config():
    """What the login page should offer."""
    from sqlalchemy import func
    s = settings()
    return {
        'needs_setup': db.session.query(func.count(User.id)).scalar() == 0,
        'sso': {'name': s['name']} if active() else None,
        'local': bool(s['local_login']) or not active(),
    }


def local_login_allowed():
    return settings()['local_login'] or active() is None


def logout_redirect():
    """Where to send the browser after sign-out to end the provider session too."""
    if session.get('via') != 'sso':
        return None
    client = active()
    return client.logout_url(session.get('id_token', ''), f'{public_url()}/login') if client else None


@sso_bp.route('/api/settings/sso', methods=['GET'])
@require_role('admin')
def get_settings():
    return jsonify({**view(), 'you_use_sso': session.get('via') == 'sso'})


@sso_bp.route('/api/settings/sso', methods=['PUT'])
@require_role('admin')
def put_settings():
    data = request.get_json(silent=True) or {}
    try:
        n = validate(data)
        eff = settings(n)
        if eff['enabled']:
            Oidc(eff).discover()  # Save and test: reachable and well-formed
        if eff['enabled'] and not eff['local_login'] and session.get('via') != 'sso':
            raise SsoError('input', f"Sign in with {eff['name']} once before turning local accounts off, "
                                    'so you know it works')
    except SsoError as e:
        return jsonify({'error': str(e)}), 400
    save(n)
    logger.info('sso: settings changed by %s: %s', current_user.username,
                'on' if settings()['enabled'] else 'off')
    return jsonify({**view(), 'you_use_sso': session.get('via') == 'sso'})

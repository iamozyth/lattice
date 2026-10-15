import json
import time
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from tests.conftest import Client, login, make_user

ISSUER = 'https://auth.example.com/application/o/lattice/'
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
JWK = {**json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key())), 'kid': 'k1', 'use': 'sig', 'alg': 'RS256'}
META = {
    'issuer': ISSUER,
    'authorization_endpoint': 'https://auth.example.com/application/o/authorize/',
    'token_endpoint': 'https://auth.example.com/application/o/token/',
    'userinfo_endpoint': 'https://auth.example.com/application/o/userinfo/',
    'jwks_uri': 'https://auth.example.com/application/o/lattice/jwks/',
    'end_session_endpoint': 'https://auth.example.com/application/o/lattice/end-session/',
}


class FakeResponse:
    def __init__(self, body, status=200):
        self._body, self.status_code, self.ok = body, status, status < 400

    def json(self):
        return self._body


class Provider:
    """Answers discovery and token requests like authentik would."""

    def __init__(self):
        self.claims = {}
        self.alg = 'RS256'

    def token(self, nonce):
        now = int(time.time())
        claims = {'iss': ISSUER, 'aud': 'lattice', 'sub': 'u-123', 'iat': now, 'exp': now + 300, 'nonce': nonce,
                  'preferred_username': 'akadmin', 'email': 'ak@example.com', 'groups': ['lattice-editors'],
                  **self.claims}
        if self.alg == 'HS256':
            return jwt.encode(claims, 'client-secret-but-at-least-32-bytes-long', algorithm='HS256')
        return jwt.encode(claims, KEY, algorithm='RS256', headers={'kid': 'k1'})

    def request(self, method, url, **kw):
        if url.endswith('/.well-known/openid-configuration'):
            return FakeResponse(META)
        if url == META['token_endpoint']:
            assert kw['auth'] == ('lattice', 'secret')
            assert kw['data']['code_verifier']
            return FakeResponse({'id_token': self.token(self.nonce), 'access_token': 'at'})
        raise AssertionError(url)


@pytest.fixture
def provider(monkeypatch):
    p = Provider()
    monkeypatch.setattr('app.sso.requests.request', p.request)
    monkeypatch.setattr(jwt.PyJWKClient, 'fetch_data', lambda self: {'keys': [JWK]})
    from app import sso
    sso._clients.clear()
    sso._used_states.clear()
    return p


@pytest.fixture
def sso_on(admin, provider):
    resp = admin.put('/api/settings/sso', {'enabled': True, 'issuer': ISSUER, 'client_id': 'lattice',
                                          'client_secret': 'secret', 'name': 'authentik'})
    assert resp.status_code == 200, resp.json
    return provider


def sign_in(app, provider, follow_code='abc'):
    c = Client(app.test_client())
    start = c.get('/auth/oidc/start')
    assert start.status_code == 302
    q = parse_qs(urlparse(start.headers['Location']).query)
    provider.nonce = q['nonce'][0]
    return c, c.get(f"/auth/oidc/callback?code={follow_code}&state={q['state'][0]}"), q


def test_settings_hide_secret_and_show_redirect_uri(admin, sso_on):
    view = admin.get('/api/settings/sso').json
    assert view['enabled'] and view['has_secret'] and view['active']
    assert '"secret"' not in json.dumps(view) and 'client_secret' not in {k for k in view if k != 'locked'}
    assert view['redirect_uri'].endswith('/auth/oidc/callback')


def test_login_page_offers_sso(anon, sso_on):
    cfg = anon.get('/api/auth/config').json
    assert cfg['sso'] == {'name': 'authentik'} and cfg['local'] is True


def test_start_uses_pkce_and_state(app, sso_on):
    c = Client(app.test_client())
    resp = c.get('/auth/oidc/start')
    q = parse_qs(urlparse(resp.headers['Location']).query)
    assert q['code_challenge_method'] == ['S256'] and q['client_id'] == ['lattice']
    assert 'lattice_oidc=' in resp.headers['Set-Cookie'] and 'HttpOnly' in resp.headers['Set-Cookie']


def test_sign_in_creates_account_with_role_from_groups(app, sso_on):
    c, resp, _ = sign_in(app, sso_on)
    assert resp.status_code == 302 and resp.headers['Location'] == '/'
    status = c.get('/api/auth/status').json
    assert status['user']['username'] == 'akadmin'
    assert status['user']['role'] == 'editor' and status['via'] == 'sso'
    assert status['user']['source'] == 'sso'


def test_group_change_updates_role(app, sso_on):
    sign_in(app, sso_on)
    sso_on.claims = {'groups': ['lattice-viewers']}
    c, _, _ = sign_in(app, sso_on)
    assert c.get('/api/auth/status').json['user']['role'] == 'viewer'


def test_no_matching_group_is_refused(app, sso_on):
    sso_on.claims = {'groups': ['staff']}
    c, resp, _ = sign_in(app, sso_on)
    assert resp.headers['Location'] == '/login?error=sso_denied'
    assert c.get('/api/auth/status').json['user'] is None


def test_never_takes_over_local_account(app, sso_on):
    make_user(app, 'akadmin', 'admin')
    c, _, _ = sign_in(app, sso_on)
    user = c.get('/api/auth/status').json['user']
    assert user['username'] == 'akadmin-2' and user['role'] == 'editor'


def test_bad_state_and_replay_are_refused(app, sso_on):
    c = Client(app.test_client())
    c.get('/auth/oidc/start')
    assert c.get('/auth/oidc/callback?code=x&state=forged').headers['Location'] == '/login?error=sso_state'
    c2, ok, q = sign_in(app, sso_on)
    assert ok.headers['Location'] == '/'
    replay = c2.get(f"/auth/oidc/callback?code=abc&state={q['state'][0]}")
    assert 'error=sso_' in replay.headers['Location']


def test_hmac_tokens_are_refused(app, sso_on):
    sso_on.alg = 'HS256'
    _, resp, _ = sign_in(app, sso_on)
    assert resp.headers['Location'] == '/login?error=sso_failed'


def test_wrong_audience_is_refused(app, sso_on):
    sso_on.claims = {'aud': 'someone-else'}
    _, resp, _ = sign_in(app, sso_on)
    assert resp.headers['Location'] == '/login?error=sso_failed'


def test_logout_ends_provider_session(app, sso_on):
    c, _, _ = sign_in(app, sso_on)
    out = c.post('/api/auth/logout').json
    assert out['redirect'].startswith(META['end_session_endpoint'])
    assert c.get('/api/subnets').status_code == 401


def test_local_login_off_needs_an_sso_session_first(admin, sso_on, app):
    resp = admin.put('/api/settings/sso', {'local_login': False})
    assert resp.status_code == 400
    sso_on.claims = {'groups': ['lattice-admins']}
    c, _, _ = sign_in(app, sso_on)
    assert c.put('/api/settings/sso', {'local_login': False}).status_code == 200
    make_user(app, 'local', 'editor')
    resp = Client(app.test_client()).post('/api/auth/login', {'username': 'local', 'password': 'password123'})
    assert resp.status_code == 403
    assert Client(app.test_client()).get('/api/auth/config').json['local'] is False


def test_enabling_checks_the_provider(admin, provider, monkeypatch):
    def down(method, url, **kw):
        import requests
        raise requests.ConnectionError('refused')
    monkeypatch.setattr('app.sso.requests.request', down)
    resp = admin.put('/api/settings/sso', {'enabled': True, 'issuer': ISSUER, 'client_id': 'lattice',
                                          'client_secret': 'secret'})
    assert resp.status_code == 400 and 'auth.example.com' in resp.json['error']


def test_http_issuer_is_rejected(admin, provider):
    resp = admin.put('/api/settings/sso', {'enabled': True, 'issuer': 'http://auth.example.com/o/',
                                          'client_id': 'lattice', 'client_secret': 'secret'})
    assert resp.status_code == 400


def test_editor_cannot_read_sso_settings(editor):
    assert editor.get('/api/settings/sso').status_code == 403


def test_sso_session_expires(app, sso_on):
    c, _, _ = sign_in(app, sso_on)
    with c.c.session_transaction() as s:
        s['sso_until'] = time.time() - 1
    assert c.get('/api/subnets').status_code == 401

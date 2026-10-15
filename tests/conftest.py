import os

import pytest
from flask_migrate import upgrade
from sqlalchemy import text

os.environ.setdefault('DATABASE_URL',
                      os.environ.get('TEST_DATABASE_URL',
                                     'postgresql://lattice:lattice@127.0.0.1:55432/lattice_test'))
os.environ.setdefault('SECRET_KEY', 'test-secret')
os.environ['LATTICE_NO_SCHEDULER'] = '1'

from app import create_app, db, limiter  # noqa: E402
from app.models import User  # noqa: E402

HEADERS = {'X-Requested-With': 'lattice'}
TABLES = 'discoveries, dhcp_ranges, ips, subnets, connectors, users'


@pytest.fixture(scope='session')
def app():
    app = create_app({'TESTING': True, 'CONNECTOR_SECRET': 'test-connector-secret'})
    with app.app_context():
        db.session.execute(text('DROP SCHEMA public CASCADE; CREATE SCHEMA public'))
        db.session.commit()
        upgrade()
    limiter.enabled = False
    return app


@pytest.fixture(autouse=True)
def clean(app):
    with app.app_context():
        db.session.execute(text(f'TRUNCATE {TABLES} RESTART IDENTITY CASCADE'))
        db.session.commit()
    yield
    with app.app_context():
        db.session.remove()


class Client:
    """Test client that sends the CSRF header and JSON by default."""

    def __init__(self, flask_client):
        self.c = flask_client

    def __getattr__(self, name):
        return getattr(self.c, name)

    def _send(self, method, url, json=None, headers=None):
        h = dict(HEADERS)
        h.update(headers or {})
        return self.c.open(url, method=method, json=json, headers=h)

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def post(self, url, json=None, headers=None):
        return self._send('POST', url, json, headers)

    def put(self, url, json=None, headers=None):
        return self._send('PUT', url, json, headers)

    def delete(self, url, headers=None):
        return self._send('DELETE', url, None, headers)


def make_user(app, username, role, password='password123'):
    with app.app_context():
        user = User(username=username, email=f'{username}@example.com', role=role, is_active=True)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user.id


def login(app, username, role):
    make_user(app, username, role)
    client = Client(app.test_client())
    resp = client.post('/api/auth/login', {'username': username, 'password': 'password123'})
    assert resp.status_code == 200, resp.json
    return client


@pytest.fixture
def anon(app):
    return Client(app.test_client())


@pytest.fixture
def admin(app):
    return login(app, 'admin', 'admin')


@pytest.fixture
def editor(app):
    return login(app, 'editor', 'editor')


@pytest.fixture
def viewer(app):
    return login(app, 'viewer', 'viewer')


@pytest.fixture
def subnet(editor):
    resp = editor.post('/api/subnets', {'name': 'lan', 'cidr': '192.168.50.0/24',
                                        'gateway': '192.168.50.1'})
    assert resp.status_code == 201, resp.json
    return resp.json

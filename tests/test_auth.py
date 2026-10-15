from tests.conftest import Client, make_user


def test_setup_creates_first_admin_once(app, anon):
    assert anon.get('/api/auth/status').json['needs_setup'] is True
    resp = anon.post('/api/auth/setup', {'username': 'root', 'email': 'r@x.io', 'password': 'longenough'})
    assert resp.status_code == 201
    assert resp.json['user']['role'] == 'admin'
    again = Client(app.test_client()).post('/api/auth/setup',
                                           {'username': 'evil', 'email': 'e@x.io', 'password': 'longenough'})
    assert again.status_code == 403


def test_register_endpoint_is_gone(anon):
    resp = anon.post('/api/auth/register', {'username': 'x', 'email': 'x@x.io', 'password': 'longenough'})
    assert resp.status_code in (404, 405)


def test_write_requires_csrf_header(editor):
    resp = editor.c.post('/api/subnets', json={'name': 'a', 'cidr': '10.0.0.0/24'})
    assert resp.status_code == 403
    resp = editor.post('/api/subnets', {'name': 'a', 'cidr': '10.0.0.0/24'})
    assert resp.status_code == 201


def test_api_requires_login(anon):
    assert anon.get('/api/subnets').status_code == 401
    assert anon.get('/').status_code == 302


def test_viewer_is_read_only(viewer, subnet):
    assert viewer.get('/api/subnets').status_code == 200
    assert viewer.post('/api/subnets', {'name': 'b', 'cidr': '10.1.0.0/24'}).status_code == 403
    assert viewer.post('/api/ips', {'address': '192.168.50.10'}).status_code == 403
    assert viewer.delete(f'/api/subnets/{subnet["id"]}').status_code == 403


def test_editor_cannot_manage_users_or_connectors_or_import(editor):
    assert editor.get('/api/auth/users').status_code == 403
    assert editor.get('/api/connectors').status_code == 403
    assert editor.post('/api/import', {'subnets': []}).status_code == 403


def test_admin_cannot_remove_last_admin(admin, app):
    me = admin.get('/api/auth/status').json['user']
    assert admin.delete(f'/api/auth/users/{me["id"]}').status_code == 400
    assert admin.put(f'/api/auth/users/{me["id"]}', {'role': 'viewer'}).status_code == 400
    assert admin.put(f'/api/auth/users/{me["id"]}', {'is_active': False}).status_code == 400


def test_password_change_revokes_other_sessions(app):
    make_user(app, 'sam', 'editor')
    first, second = Client(app.test_client()), Client(app.test_client())
    for c in (first, second):
        assert c.post('/api/auth/login', {'username': 'sam', 'password': 'password123'}).status_code == 200
    resp = first.post('/api/auth/password', {'current_password': 'password123', 'new_password': 'newpassword1'})
    assert resp.status_code == 200
    assert first.get('/api/subnets').status_code == 200
    assert second.get('/api/subnets').status_code == 401


def test_disabled_user_loses_session(admin, app):
    make_user(app, 'kim', 'editor')
    kim = Client(app.test_client())
    kim.post('/api/auth/login', {'username': 'kim', 'password': 'password123'})
    users = admin.get('/api/auth/users').json['items']
    kim_id = next(u['id'] for u in users if u['username'] == 'kim')
    assert admin.put(f'/api/auth/users/{kim_id}', {'is_active': False}).status_code == 200
    assert kim.get('/api/subnets').status_code == 401


def test_errors_do_not_leak_internals(editor):
    resp = editor.post('/api/subnets', {'name': 'x', 'cidr': 'not-a-cidr'})
    assert resp.status_code == 400
    assert 'Traceback' not in resp.get_data(as_text=True)


def test_security_headers(admin):
    resp = admin.get('/')
    csp = resp.headers['Content-Security-Policy']
    assert "script-src 'self'" in csp and 'unsafe-inline' not in csp
    assert 'Access-Control-Allow-Origin' not in resp.headers


def test_logout_also_ends_remember_me(app):
    make_user(app, 'rita', 'editor')
    c = Client(app.test_client())
    assert c.post('/api/auth/login', {'username': 'rita', 'password': 'password123', 'remember': True}).status_code == 200
    assert c.c.get_cookie('remember_token') is not None
    c.post('/api/auth/logout')
    assert c.c.get_cookie('remember_token') is None
    assert c.get('/api/subnets').status_code == 401

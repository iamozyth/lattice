from app import db
from app.discovery import record_hosts


def changes(c, **params):
    q = '&'.join(f'{k}={v}' for k, v in params.items())
    resp = c.get(f'/api/changes?{q}')
    assert resp.status_code == 200, resp.json
    return resp.json['items']


def test_create_update_delete_are_recorded_with_the_actor(editor):
    s = editor.post('/api/subnets', {'name': 'lan', 'cidr': '192.168.7.0/24'}).json
    ip = editor.post('/api/ips', {'subnet_id': s['id'], 'address': '192.168.7.10', 'hostname': 'nas'}).json
    editor.put(f'/api/ips/{ip["id"]}', {'hostname': 'nas-2', 'status': 'reserved'})
    editor.delete(f'/api/ips/{ip["id"]}')

    log = changes(editor, entity='ip', id=ip['id'])
    assert [c['action'] for c in log] == ['delete', 'update', 'create']  # newest first
    update = log[1]
    assert update['username'] == 'editor' and update['label'] == '192.168.7.10'
    assert update['diff'] == {'hostname': ['nas', 'nas-2'], 'status': ['in-use', 'reserved']}
    assert log[2]['diff']['address'] == [None, '192.168.7.10']
    assert changes(editor, entity='subnet')[0]['diff']['cidr'] == [None, '192.168.7.0/24']


def test_subnet_filter_includes_its_addresses(editor, subnet):
    editor.post('/api/ips', {'subnet_id': subnet['id'], 'address': '192.168.50.9'})
    entities = {c['entity'] for c in changes(editor, subnet_id=subnet['id'])}
    assert entities == {'subnet', 'ip'}


def test_scan_updates_are_not_noise_but_filled_macs_are_system_changes(app, editor, subnet):
    ip = editor.post('/api/ips', {'subnet_id': subnet['id'], 'address': '192.168.50.30'}).json
    with app.app_context():
        record_hosts(subnet['id'], [{'address': '192.168.50.30'}], source='scan')  # only last_seen
        record_hosts(subnet['id'], [{'address': '192.168.50.30', 'mac_address': 'aa:bb:cc:00:00:30'}], source='scan')
        db.session.remove()
    log = changes(editor, entity='ip', id=ip['id'])
    assert [c['action'] for c in log] == ['update', 'create']
    assert log[0]['username'] == 'system' and log[0]['diff'] == {'mac_address': [None, 'AA:BB:CC:00:00:30']}


def test_secrets_are_masked(admin, app):
    from tests.conftest import make_user
    uid = make_user(app, 'kim', 'editor')
    admin.put(f'/api/auth/users/{uid}', {'password': 'another-password', 'role': 'viewer'})
    log = changes(admin, entity='user', id=uid)
    assert log[0]['diff'] == {'password_hash': '(changed)', 'role': ['editor', 'viewer']}
    admin.post('/api/connectors', {'name': 'udm', 'type': 'unifi', 'config': {
        'base_url': 'https://192.168.1.1', 'api_key': 'very-secret-key'}})
    entry = changes(admin, entity='connector')[0]
    assert 'very-secret-key' not in str(entry) and entry['diff']['config_encrypted'] == '(changed)'


def test_paging_with_before_cursor(editor):
    for n in range(5):
        editor.post('/api/subnets', {'name': f's{n}', 'cidr': f'10.{n}.0.0/24'})
    first = editor.get('/api/changes?limit=2').json
    assert len(first['items']) == 2 and first['next']
    second = editor.get(f"/api/changes?limit=2&before={first['next']}").json
    assert second['items'][0]['id'] < first['items'][-1]['id']


def test_search_by_label_and_user(editor, admin):
    editor.post('/api/subnets', {'name': 'garage', 'cidr': '10.9.0.0/24'})
    admin.post('/api/subnets', {'name': 'attic', 'cidr': '10.8.0.0/24'})
    assert [c['label'] for c in changes(editor, q='garage')] == ['garage (10.9.0.0/24)']
    assert {c['username'] for c in changes(editor, user='admin')} == {'admin'}


def test_viewers_can_read_and_anonymous_cannot(viewer, anon):
    assert viewer.get('/api/changes').status_code == 200
    assert anon.get('/api/changes').status_code == 401


def test_purge_drops_old_entries(app, editor):
    from datetime import datetime, timedelta
    from app.history import purge
    from app.models import Change
    editor.post('/api/subnets', {'name': 'old', 'cidr': '10.7.0.0/24'})
    with app.app_context():
        Change.query.update({'at': datetime.utcnow() - timedelta(days=400)})
        db.session.commit()
        assert purge(365) == 2  # the fixture's editor account and the subnet
        db.session.remove()
    assert changes(editor) == []

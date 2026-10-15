from app.connectors.base import ConnectorError
from app.connectors.unifi import UniFiConnector


def _create(admin):
    return admin.post('/api/connectors', {'name': 'udm', 'type': 'unifi', 'config': {
        'base_url': 'https://192.168.1.1', 'api_key': 'secret-key'}})


def test_create_hides_secrets(admin):
    resp = _create(admin)
    assert resp.status_code == 201
    assert 'secret-key' not in resp.get_data(as_text=True)
    assert resp.json['details']['auth'] == 'api_key'


def test_rejects_non_http_urls(admin):
    resp = admin.post('/api/connectors', {'name': 'x', 'type': 'unifi', 'config': {
        'base_url': 'file:///etc/passwd', 'api_key': 'k'}})
    assert resp.status_code == 400


def test_edit_keeps_secret_when_blank(admin):
    cid = _create(admin).json['id']
    resp = admin.put(f'/api/connectors/{cid}', {'config': {'base_url': 'https://10.0.0.1', 'api_key': ''}})
    assert resp.status_code == 200
    assert resp.json['details']['auth'] == 'api_key'


def test_sync_preview_and_apply(admin, monkeypatch):
    admin.post('/api/subnets', {'name': 'lan', 'cidr': '192.168.1.0/24'})
    admin.post('/api/ips', {'address': '192.168.1.10', 'hostname': 'nas'})
    clients = [{'ip': '192.168.1.10', 'mac': 'aa:bb:cc:dd:ee:10', 'hostname': 'other'},
               {'ip': '192.168.1.20', 'mac': 'aa:bb:cc:dd:ee:20', 'hostname': 'phone'},
               {'ip': '172.16.0.1'}, {'ip': None}]
    monkeypatch.setattr(UniFiConnector, 'fetch', lambda self: clients)
    cid = _create(admin).json['id']
    preview = admin.post(f'/api/connectors/{cid}/sync?dry_run=true').json
    assert [a['ip'] for a in preview['add']] == ['192.168.1.20']
    assert preview['update'][0]['changes'] == {'mac_address': 'AA:BB:CC:DD:EE:10'}
    assert len(preview['skip']) == 2
    assert admin.get('/api/ips').json['total'] == 1
    applied = admin.post(f'/api/connectors/{cid}/sync').json
    assert applied['dry_run'] is False
    assert admin.get('/api/ips').json['total'] == 2


def test_sync_error_is_reported_without_body(admin, monkeypatch):
    def boom(self):
        raise ConnectorError('UniFi rejected the credentials')
    monkeypatch.setattr(UniFiConnector, 'fetch', boom)
    cid = _create(admin).json['id']
    resp = admin.post(f'/api/connectors/{cid}/test')
    assert resp.status_code == 502
    assert resp.json['error'] == 'UniFi rejected the credentials'

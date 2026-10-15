import pytest

from app import db
from app.discovery import record_hosts
from app.scanner import OutputParser, ScanError, build_command


@pytest.mark.parametrize('value', ['-oN/tmp/x', '--script=foo', 'example.com', '10.0.0.1;id', '', '10.0.0.0/33'])
def test_nmap_rejects_anything_but_addresses(value):
    with pytest.raises(ScanError):
        build_command('ping', [value])


def test_nmap_command_shape():
    assert build_command('ping', ['192.168.1.7/24']) == ['nmap', '-sn', '--', '192.168.1.0/24']
    assert build_command('ping', ['2001:DB8::1']) == ['nmap', '-sn', '-6', '--', '2001:db8::1']
    with pytest.raises(ScanError):
        build_command('ping', ['10.0.0.1', '::1'])


def test_verify_ip_endpoint_is_gone(editor):
    assert editor.post('/api/scanner/verify-ip', {'address': '-oN/tmp/x', 'subnet_id': 1}).status_code == 404


def test_parser_only_reports_hosts_that_are_up():
    output = """Starting Nmap 7.94
Nmap scan report for router.lan (192.168.50.1)
Host is up (0.0010s latency).
MAC Address: aa:bb:cc:dd:ee:01 (Ubiquiti)
Nmap scan report for 192.168.50.7
Host is up (0.0020s latency).
MAC Address: AA:BB:CC:DD:EE:07 (Unknown)
Nmap done: 256 IP addresses (2 hosts up) scanned in 2.1 seconds"""
    p = OutputParser()
    for line in output.splitlines():
        p.feed(line)
    hosts = p.close()
    assert [h['address'] for h in hosts] == ['192.168.50.1', '192.168.50.7']
    assert hosts[0]['hostname'] == 'router.lan'
    assert hosts[0]['vendor'] == 'Ubiquiti'
    assert hosts[1]['vendor'] is None
    p2 = OutputParser()
    for line in ['Nmap done: 1 IP address (0 hosts up) scanned in 3.0 seconds']:
        p2.feed(line)
    assert p2.close() == []


def test_drift_report(app, editor, subnet):
    sid = subnet['id']
    editor.post('/api/ips', {'subnet_id': sid, 'address': '192.168.50.10', 'hostname': 'nas',
                             'mac_address': '00:00:00:00:00:10'})
    editor.post('/api/ips', {'subnet_id': sid, 'address': '192.168.50.11', 'hostname': 'NAS'})
    editor.post('/api/ips', {'subnet_id': sid, 'address': '192.168.50.12', 'status': 'in-use'})
    with app.app_context():
        record_hosts(sid, [
            {'address': '192.168.50.10', 'mac_address': '00:00:00:00:00:99'},
            {'address': '192.168.50.50', 'hostname': 'phone', 'mac_address': 'aa:aa:aa:aa:aa:aa'},
            {'address': '10.0.0.1'},
        ], source='scan', full_sweep=True)
        db.session.remove()
    drift = editor.get('/api/drift').json
    assert [d['address'] for d in drift['undocumented']] == ['192.168.50.50']
    offline = [i['address'] for i in drift['offline']]
    assert '192.168.50.12' in offline and '192.168.50.10' not in offline
    types = {c['type'] for c in drift['conflicts']}
    assert {'duplicate_hostname', 'mac_mismatch'} <= types

    disc_id = drift['undocumented'][0]['id']
    assert editor.post(f'/api/discoveries/{disc_id}/ignore', {}).status_code == 200
    assert editor.get('/api/drift').json['counts']['undocumented'] == 0


def test_documented_ip_gets_last_seen_and_mac(app, editor, subnet):
    ip = editor.post('/api/ips', {'subnet_id': subnet['id'], 'address': '192.168.50.30'}).json
    assert ip['last_seen'] is None
    with app.app_context():
        record_hosts(subnet['id'], [{'address': '192.168.50.30', 'mac_address': 'aa:bb:cc:00:00:30'}],
                     source='scan')
        db.session.remove()
    ip = editor.get(f'/api/ips/{ip["id"]}').json
    assert ip['last_seen'] and ip['mac_address'] == 'AA:BB:CC:00:00:30'


def test_import_discoveries(app, editor, subnet):
    with app.app_context():
        record_hosts(subnet['id'], [{'address': '192.168.50.77', 'hostname': 'tv'}], source='scan')
        db.session.remove()
    resp = editor.post(f'/api/subnets/{subnet["id"]}/discoveries/import', {'addresses': ['192.168.50.77']})
    assert resp.json['created'] == ['192.168.50.77']
    assert editor.get('/api/drift').json['counts']['undocumented'] == 0


def test_scheduler_sweep_runs_in_app_context(app, editor, subnet, monkeypatch):
    from app import scheduler
    monkeypatch.setattr(scheduler, 'run_scan', lambda kind, targets: [{'address': '192.168.50.9'}])
    scheduler.sweep_all(app)
    drift = editor.get('/api/drift').json
    assert [d['address'] for d in drift['undocumented']] == ['192.168.50.9']


def test_update_check_knows_when_build_is_newer(monkeypatch):
    from app import updates
    monkeypatch.setattr(updates, 'latest_release', lambda: {'tag_name': 'v1.0.0-beta.1', 'html_url': 'x'})
    r = updates.check_for_updates('1.0.0-beta.2')
    assert r['ahead'] and not r['update_available']
    r = updates.check_for_updates('1.0.0-beta.1')
    assert not r['ahead'] and not r['update_available']
    monkeypatch.setattr(updates, 'latest_release', lambda: {'tag_name': 'v1.0.0', 'html_url': 'x'})
    assert updates.check_for_updates('1.0.0-beta.2')['update_available']


def test_subnet_reports_its_running_scan_so_a_reloaded_page_can_reattach(editor, subnet, monkeypatch):
    import threading
    from app import discovery, scanner
    release = threading.Event()

    def slow_scan(scan_type, values, on_line=None, should_stop=None):
        release.wait(5)
        return []
    monkeypatch.setattr(discovery, 'nmap_available', lambda: True)
    monkeypatch.setattr(scanner, 'run_scan', slow_scan)

    assert editor.get(f"/api/subnets/{subnet['id']}").json['scan_job_id'] is None
    job_id = editor.post(f"/api/subnets/{subnet['id']}/scans", {'scan_type': 'ping'}).json['job_id']
    assert editor.get(f"/api/subnets/{subnet['id']}").json['scan_job_id'] == job_id
    release.set()
    for _ in range(50):
        if editor.get(f'/api/scans/{job_id}').json['status'] != 'running':
            break
        threading.Event().wait(0.05)
    assert editor.get(f"/api/subnets/{subnet['id']}").json['scan_job_id'] is None


def test_a_scanned_gateway_stays_the_gateway(app, editor, subnet):
    with app.app_context():
        record_hosts(subnet['id'], [{'address': '192.168.50.1'}, {'address': '192.168.50.9'}], source='scan')
    cell = lambda a: next(c for c in editor.get(f"/api/subnets/{subnet['id']}/map").json['cells'] if c['address'] == a)
    assert cell('192.168.50.1')['state'] == 'gateway'
    undocumented = [d['address'] for d in editor.get('/api/drift').json['undocumented']]
    assert undocumented == ['192.168.50.9']  # the gateway is known, not drift

    # Documenting the router as an address keeps it a gateway on the map, but editable
    ip = editor.post('/api/ips', {'subnet_id': subnet['id'], 'address': '192.168.50.1', 'hostname': 'router'}).json
    assert (cell('192.168.50.1')['state'], cell('192.168.50.1')['id']) == ('gateway', ip['id'])

import csv
import io


def _ips(c, subnet_id, *addresses, **extra):
    return [c.post('/api/ips', {'subnet_id': subnet_id, 'address': a, **extra}).json['id'] for a in addresses]


# --- bulk edit ---------------------------------------------------------------

def test_bulk_update_sets_fields_and_tags(editor, subnet):
    ids = _ips(editor, subnet['id'], '192.168.50.5', '192.168.50.6', '192.168.50.7', tags=['old'])
    resp = editor.post('/api/ips/bulk-update', {'ids': ids[:2], 'set': {'status': 'reserved', 'owner': 'Ops'},
                                               'add_tags': ['printers'], 'remove_tags': ['old']})
    assert resp.status_code == 200 and resp.json == {'updated': 2}
    items = {i['address']: i for i in editor.get('/api/ips').json['items']}
    assert items['192.168.50.5']['status'] == 'reserved' and items['192.168.50.5']['owner'] == 'Ops'
    assert items['192.168.50.5']['tags'] == ['printers']
    assert items['192.168.50.7']['status'] == 'in-use' and items['192.168.50.7']['tags'] == ['old']
    assert len(editor.get('/api/changes?entity=ip&limit=200').json['items']) == 5  # 3 creates, 2 updates


def test_bulk_update_validates_and_is_capped(editor, subnet):
    ids = _ips(editor, subnet['id'], '192.168.50.5')
    assert editor.post('/api/ips/bulk-update', {'ids': ids, 'set': {'status': 'bogus'}}).status_code == 400
    assert editor.post('/api/ips/bulk-update', {'ids': ids, 'set': {'address': '10.0.0.1'}}).status_code == 400
    assert editor.post('/api/ips/bulk-update', {'ids': list(range(1001)), 'set': {'owner': 'x'}}).status_code == 400


def test_bulk_delete_and_roles(editor, viewer, subnet):
    ids = _ips(editor, subnet['id'], '192.168.50.5', '192.168.50.6')
    assert viewer.post('/api/ips/bulk-delete', {'ids': ids}).status_code == 403
    assert editor.post('/api/ips/bulk-delete', {'ids': ids}).json == {'deleted': 2}
    assert editor.get('/api/ips').json['total'] == 0


# --- CSV export ----------------------------------------------------------------

def _rows(text):
    return list(csv.DictReader(io.StringIO(text)))


def test_csv_export_of_addresses_follows_filters(editor, subnet):
    _ips(editor, subnet['id'], '192.168.50.5', tags=['a', 'b'], hostname='nas')
    _ips(editor, subnet['id'], '192.168.50.6', status='reserved')
    resp = editor.get('/api/export.csv?type=ips&status=reserved')
    assert resp.status_code == 200 and resp.mimetype == 'text/csv'
    assert 'attachment' in resp.headers['Content-Disposition']
    rows = _rows(resp.get_data(as_text=True))
    assert [r['address'] for r in rows] == ['192.168.50.6']
    full = _rows(editor.get('/api/export.csv?type=ips').get_data(as_text=True))
    assert full[0]['tags'] == 'a;b' and full[0]['subnet'] == '192.168.50.0/24' and full[0]['hostname'] == 'nas'


def test_csv_export_neutralises_formulas(editor, subnet):
    _ips(editor, subnet['id'], '192.168.50.5', hostname='=HYPERLINK("http://x")', owner='+1-555')
    row = _rows(editor.get('/api/export.csv?type=ips').get_data(as_text=True))[0]
    assert row['hostname'] == '\'=HYPERLINK("http://x")' and row['owner'] == "'+1-555"


def test_csv_export_of_subnets(editor):
    editor.post('/api/vlans', {'vid': 10, 'name': 'Servers'})
    editor.post('/api/subnets', {'name': 'lan', 'cidr': '10.0.0.0/24', 'vlan': 10, 'tags': ['home']})
    row = _rows(editor.get('/api/export.csv?type=subnets').get_data(as_text=True))[0]
    assert (row['name'], row['cidr'], row['vlan'], row['vlan_name'], row['tags']) == ('lan', '10.0.0.0/24', '10', 'Servers', 'home')


# --- CSV import ----------------------------------------------------------------

def _import(c, text, type_='ips', dry=True):
    return c.post(f"/api/import/csv?type={type_}{'&dry_run=1' if dry else ''}", {'csv': text})


def test_csv_import_preview_changes_nothing_then_apply(editor, subnet):
    _ips(editor, subnet['id'], '192.168.50.5', hostname='old')
    text = 'address,hostname,status\n192.168.50.5,new,\n192.168.50.6,printer,reserved\n10.9.9.9,nowhere,\n'
    preview = _import(editor, text)
    assert preview.status_code == 200
    assert [r['action'] for r in preview.json['rows']] == ['update', 'create', 'error']
    assert preview.json['counts'] == {'create': 1, 'update': 1, 'unchanged': 0, 'error': 1}
    assert editor.get('/api/ips').json['total'] == 1  # dry run wrote nothing
    applied = _import(editor, text, dry=False)
    assert applied.status_code == 400 and 'line 4' in applied.json['error']  # errors block the apply
    ok = _import(editor, 'address,hostname,status\n192.168.50.5,new,\n192.168.50.6,printer,reserved\n', dry=False)
    assert ok.status_code == 200 and ok.json['counts']['create'] == 1
    items = {i['address']: i for i in editor.get('/api/ips').json['items']}
    assert items['192.168.50.5']['hostname'] == 'new' and items['192.168.50.5']['status'] == 'in-use'
    assert items['192.168.50.6']['status'] == 'reserved'


def test_csv_import_understands_phpipam_headers_and_semicolons(editor, subnet):
    text = 'ip_addr;hostname;mac;description;tag\n192.168.50.7;cam;aa-bb-cc-dd-ee-ff;front door;cctv\n'
    rows = _import(editor, text).json['rows']
    assert rows[0]['action'] == 'create'
    _import(editor, text, dry=False)
    ip = editor.get('/api/ips').json['items'][0]
    assert ip['mac_address'] == 'AA:BB:CC:DD:EE:FF' and ip['description'] == 'front door' and ip['tags'] == ['cctv']


def test_csv_import_unchanged_rows(editor, subnet):
    _ips(editor, subnet['id'], '192.168.50.5', hostname='same')
    rows = _import(editor, 'address,hostname\n192.168.50.5,same\n').json['rows']
    assert rows[0]['action'] == 'unchanged'


def test_csv_import_subnets(editor):
    text = 'name,cidr,vlan,gateway,tags\nlan,10.1.0.0/24,20,10.1.0.1,home;core\n'
    assert _import(editor, text, 'subnets').json['counts']['create'] == 1
    assert _import(editor, text, 'subnets', dry=False).status_code == 200
    s = editor.get('/api/subnets').json['items'][0]
    assert s['vlan'] == 20 and s['gateway'] == '10.1.0.1' and s['tags'] == ['core', 'home']


def test_csv_import_limits(editor, viewer):
    assert viewer.post('/api/import/csv?type=ips', {'csv': 'address\n'}).status_code == 403
    assert _import(editor, 'hostname\nx\n').status_code == 400  # no address column
    big = 'address\n' + '\n'.join(f'10.0.{i // 256}.{i % 256}' for i in range(10001))
    assert _import(editor, big).status_code == 400

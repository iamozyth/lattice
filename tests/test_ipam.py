import time


def test_cidr_is_normalized_and_unique(editor):
    resp = editor.post('/api/subnets', {'name': 'a', 'cidr': '10.0.0.7/24'})
    assert resp.status_code == 201
    assert resp.json['cidr'] == '10.0.0.0/24'
    dup = editor.post('/api/subnets', {'name': 'b', 'cidr': '10.0.0.0/255.255.255.0'})
    assert dup.status_code == 409


def test_overlap_is_a_warning(editor):
    editor.post('/api/subnets', {'name': 'big', 'cidr': '10.0.0.0/16'})
    resp = editor.post('/api/subnets', {'name': 'small', 'cidr': '10.0.5.0/24'})
    assert resp.status_code == 201
    assert any('big' in w for w in resp.json['warnings'])


def test_ip_validation(editor, subnet):
    sid = subnet['id']
    assert editor.post('/api/ips', {'subnet_id': sid, 'address': '10.9.9.9'}).status_code == 400
    assert editor.post('/api/ips', {'subnet_id': sid, 'address': '192.168.50.5', 'status': 'bogus'}).status_code == 400
    assert editor.post('/api/ips', {'subnet_id': sid, 'address': '192.168.50.5', 'mac_address': 'zz'}).status_code == 400
    ok = editor.post('/api/ips', {'address': '192.168.50.5', 'mac_address': 'aa-bb-cc-dd-ee-ff'})
    assert ok.status_code == 201
    assert ok.json['subnet_id'] == sid
    assert ok.json['mac_address'] == 'AA:BB:CC:DD:EE:FF'
    assert editor.post('/api/ips', {'address': '192.168.50.5'}).status_code == 409


def test_ipv6_addresses_are_canonical(editor):
    s = editor.post('/api/subnets', {'name': 'v6', 'cidr': '2001:DB8::/64'}).json
    assert s['cidr'] == '2001:db8::/64'
    a = editor.post('/api/ips', {'subnet_id': s['id'], 'address': '2001:DB8:0::1'})
    assert a.json['address'] == '2001:db8::1'
    assert editor.post('/api/ips', {'subnet_id': s['id'], 'address': '2001:db8::1'}).status_code == 409


def test_free_addresses_on_huge_ipv6_is_fast(editor):
    s = editor.post('/api/subnets', {'name': 'v6', 'cidr': '2001:db8::/48'}).json
    start = time.monotonic()
    resp = editor.get(f'/api/subnets/{s["id"]}/free?limit=5')
    assert resp.status_code == 200
    assert resp.json['next'] == '2001:db8::1'
    assert time.monotonic() - start < 2


def test_cidr_change_cannot_orphan_ips(editor, subnet):
    editor.post('/api/ips', {'subnet_id': subnet['id'], 'address': '192.168.50.200'})
    resp = editor.put(f'/api/subnets/{subnet["id"]}', {'cidr': '192.168.50.0/25'})
    assert resp.status_code == 400


def test_sorting_is_numeric_across_pages(editor, subnet):
    for last in (10, 2, 100, 9):
        editor.post('/api/ips', {'subnet_id': subnet['id'], 'address': f'192.168.50.{last}'})
    page1 = editor.get('/api/ips?per_page=2&page=1').json
    page2 = editor.get('/api/ips?per_page=2&page=2').json
    assert [i['address'] for i in page1['items'] + page2['items']] == [
        '192.168.50.2', '192.168.50.9', '192.168.50.10', '192.168.50.100']
    assert editor.get('/api/ips?per_page=0&page=-3').status_code == 200


def test_search_escapes_wildcards(editor, subnet):
    editor.post('/api/ips', {'subnet_id': subnet['id'], 'address': '192.168.50.3', 'hostname': 'abc'})
    assert editor.get('/api/ips?search=%25').json['total'] == 0


def test_bulk_add(editor, subnet):
    resp = editor.post('/api/ips/bulk', {'subnet_id': subnet['id'], 'ips': [
        {'address': '192.168.50.20'}, {'address': '192.168.50.20'},
        {'address': '10.0.0.1'}, {'address': '192.168.50.21', 'status': 'nope'}]})
    assert resp.json['created'] == ['192.168.50.20']
    assert len(resp.json['errors']) == 3


def test_lookup_picks_most_specific(editor):
    editor.post('/api/subnets', {'name': 'big', 'cidr': '10.0.0.0/16'})
    editor.post('/api/subnets', {'name': 'small', 'cidr': '10.0.5.0/24'})
    resp = editor.get('/api/lookup/10.0.5.9')
    assert resp.json['subnet']['name'] == 'small'


def test_dhcp_ranges_and_next_free(editor, subnet):
    sid = subnet['id']
    r = editor.post(f'/api/subnets/{sid}/dhcp-ranges', {'start': '192.168.50.2', 'end': '192.168.50.99'})
    assert r.status_code == 201
    assert editor.post(f'/api/subnets/{sid}/dhcp-ranges',
                       {'start': '192.168.50.50', 'end': '192.168.50.120'}).status_code == 400
    assert editor.post(f'/api/subnets/{sid}/dhcp-ranges',
                       {'start': '10.0.0.1', 'end': '10.0.0.2'}).status_code == 400
    free = editor.get(f'/api/subnets/{sid}/free').json
    assert free['next'] == '192.168.50.100'
    warn = editor.post('/api/ips', {'subnet_id': sid, 'address': '192.168.50.10'}).json
    assert any('DHCP pool' in w for w in warn['warnings'])


def test_subnet_map(editor, subnet):
    sid = subnet['id']
    editor.post(f'/api/subnets/{sid}/dhcp-ranges', {'start': '192.168.50.100', 'end': '192.168.50.110'})
    editor.post('/api/ips', {'subnet_id': sid, 'address': '192.168.50.5', 'status': 'reserved'})
    cells = {c['address']: c for c in editor.get(f'/api/subnets/{sid}/map').json['cells']}
    assert len(cells) == 256
    assert cells['192.168.50.0']['state'] == 'reserved-net'
    assert cells['192.168.50.1']['state'] == 'gateway'
    assert cells['192.168.50.5']['state'] == 'reserved'
    assert cells['192.168.50.105'].get('pool') is True
    big = editor.post('/api/subnets', {'name': 'big', 'cidr': '10.0.0.0/16'}).json
    assert editor.get(f'/api/subnets/{big["id"]}/map').status_code == 400


def test_utilization_counts_only_used_statuses(editor, subnet):
    editor.post('/api/ips', {'subnet_id': subnet['id'], 'address': '192.168.50.5', 'status': 'available'})
    editor.post('/api/ips', {'subnet_id': subnet['id'], 'address': '192.168.50.6', 'status': 'in-use'})
    s = editor.get(f'/api/subnets/{subnet["id"]}').json
    assert s['used_ips'] == 1 and s['ip_count'] == 2


def test_export_import_roundtrip(admin):
    s = admin.post('/api/subnets', {'name': 'lan', 'cidr': '192.168.1.0/24'}).json
    admin.post(f'/api/subnets/{s["id"]}/dhcp-ranges', {'start': '192.168.1.100', 'end': '192.168.1.200'})
    admin.post('/api/ips', {'subnet_id': s['id'], 'address': '192.168.1.10', 'hostname': 'nas'})
    dump = admin.get('/api/export').json
    resp = admin.post('/api/import?mode=replace', dump)
    assert resp.status_code == 200, resp.json
    assert resp.json == {'subnets': 1, 'ips': 1, 'dhcp_ranges': 1}
    again = admin.post('/api/import', dump).json
    assert again == {'subnets': 0, 'ips': 0, 'dhcp_ranges': 0}


def test_failed_replace_import_changes_nothing(admin):
    admin.post('/api/subnets', {'name': 'keep', 'cidr': '192.168.1.0/24'})
    bad = {'subnets': [{'name': 'x', 'cidr': '10.0.0.0/24', 'ips': [{'address': 'nonsense'}]}]}
    resp = admin.post('/api/import?mode=replace', bad)
    assert resp.status_code == 400
    names = [s['name'] for s in admin.get('/api/subnets').json['items']]
    assert names == ['keep']

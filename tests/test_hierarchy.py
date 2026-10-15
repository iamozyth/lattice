def _subnet(c, name, cidr):
    resp = c.post('/api/subnets', {'name': name, 'cidr': cidr})
    assert resp.status_code == 201, resp.json
    return resp.json


def test_parent_is_most_specific_container_of_same_version(editor):
    site = _subnet(editor, 'site', '10.10.0.0/16')
    lan = _subnet(editor, 'lan', '10.10.1.0/24')
    small = _subnet(editor, 'small', '10.10.1.0/26')
    _subnet(editor, 'v6', '2001:db8::/48')
    items = {s['name']: s for s in editor.get('/api/subnets').json['items']}
    assert items['site']['parent_id'] is None and items['site']['depth'] == 0
    assert items['lan']['parent_id'] == site['id'] and items['lan']['depth'] == 1
    assert items['small']['parent_id'] == lan['id'] and items['small']['depth'] == 2
    assert items['v6']['parent_id'] is None
    assert items['site']['children'] == 1 and items['lan']['children'] == 1
    assert small['inside'] == {'id': lan['id'], 'name': 'lan', 'cidr': '10.10.1.0/24'}


def test_list_is_ordered_as_a_tree(editor):
    _subnet(editor, 'b-lan', '10.10.1.0/24')
    _subnet(editor, 'other', '192.168.1.0/24')
    _subnet(editor, 'site', '10.10.0.0/16')
    _subnet(editor, 'a-lan', '10.10.0.0/24')
    names = [s['name'] for s in editor.get('/api/subnets').json['items']]
    assert names == ['site', 'a-lan', 'b-lan', 'other']


def test_free_blocks_around_children(editor):
    site = _subnet(editor, 'site', '10.10.0.0/16')
    _subnet(editor, 'first', '10.10.0.0/24')
    _subnet(editor, 'third', '10.10.2.0/24')
    resp = editor.get(f'/api/subnets/{site["id"]}/free-blocks?prefix=24&limit=3')
    assert resp.status_code == 200
    assert resp.json['next'] == ['10.10.1.0/24', '10.10.3.0/24', '10.10.4.0/24']
    assert resp.json['free'][:3] == ['10.10.1.0/24', '10.10.3.0/24', '10.10.4.0/22']
    assert resp.json['free_addresses'] == 65536 - 512
    listed = {x['name']: x for x in editor.get('/api/subnets').json['items']}
    assert listed['site']['allocated'] == 0.8 and listed['first']['allocated'] == 0


def test_free_blocks_rejects_prefix_outside_parent(editor):
    site = _subnet(editor, 'site', '10.10.0.0/16')
    assert editor.get(f'/api/subnets/{site["id"]}/free-blocks?prefix=8').status_code == 400


def test_creating_child_moves_addresses_and_deleting_moves_them_back(editor):
    site = _subnet(editor, 'site', '10.10.0.0/16')
    editor.post('/api/ips', {'subnet_id': site['id'], 'address': '10.10.5.10', 'hostname': 'nas'})
    editor.post('/api/ips', {'subnet_id': site['id'], 'address': '10.10.9.1'})
    child = editor.post('/api/subnets', {'name': 'five', 'cidr': '10.10.5.0/24'}).json
    assert child['moved'] == 1
    assert [i['address'] for i in editor.get(f'/api/ips?subnet_id={child["id"]}').json['items']] == ['10.10.5.10']
    assert editor.delete(f'/api/subnets/{child["id"]}').status_code == 204
    left = [i['address'] for i in editor.get(f'/api/ips?subnet_id={site["id"]}').json['items']]
    assert left == ['10.10.5.10', '10.10.9.1']


def test_deleting_top_level_subnet_deletes_its_addresses(editor):
    lan = _subnet(editor, 'lan', '192.168.1.0/24')
    editor.post('/api/ips', {'subnet_id': lan['id'], 'address': '192.168.1.5'})
    editor.delete(f'/api/subnets/{lan["id"]}')
    assert editor.get('/api/ips').json['total'] == 0


def test_new_address_goes_to_most_specific_subnet(editor):
    _subnet(editor, 'site', '10.10.0.0/16')
    child = _subnet(editor, 'five', '10.10.5.0/24')
    ip = editor.post('/api/ips', {'address': '10.10.5.7'}).json
    assert ip['subnet_id'] == child['id']


def test_map_shows_child_ranges(editor):
    parent = _subnet(editor, 'lan', '192.168.0.0/23')
    child = _subnet(editor, 'upper', '192.168.1.0/24')
    cells = {c['address']: c for c in editor.get(f'/api/subnets/{parent["id"]}/map').json['cells']}
    assert cells['192.168.1.20']['state'] == 'child' and cells['192.168.1.20']['child_id'] == child['id']
    assert cells['192.168.0.20']['state'] == 'free'

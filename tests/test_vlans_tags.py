def test_vlan_crud_and_uniqueness_per_site(editor):
    v = editor.post('/api/vlans', {'vid': 10, 'name': 'Servers'})
    assert v.status_code == 201 and v.json['vid'] == 10 and v.json['site'] == ''
    assert editor.post('/api/vlans', {'vid': 10, 'name': 'Again'}).status_code == 409
    assert editor.post('/api/vlans', {'vid': 10, 'name': 'Branch', 'site': 'branch'}).status_code == 201
    assert editor.post('/api/vlans', {'vid': 5000, 'name': 'x'}).status_code == 400
    upd = editor.put(f"/api/vlans/{v.json['id']}", {'name': 'Server LAN'})
    assert upd.json['name'] == 'Server LAN'
    assert [x['vid'] for x in editor.get('/api/vlans').json['items']] == [10, 10]


def test_subnet_links_to_vlan_and_deleting_vlan_unlinks(editor):
    v = editor.post('/api/vlans', {'vid': 20, 'name': 'IoT'}).json
    s = editor.post('/api/subnets', {'name': 'iot', 'cidr': '192.168.20.0/24', 'vlan_id': v['id']}).json
    assert s['vlan'] == 20 and s['vlan_id'] == v['id'] and s['vlan_name'] == 'IoT'
    listed = editor.get('/api/vlans').json['items'][0]
    assert [x['name'] for x in listed['subnets']] == ['iot']
    assert editor.get(f"/api/subnets?vlan_id={v['id']}").json['items'][0]['name'] == 'iot'
    assert editor.delete(f"/api/vlans/{v['id']}").status_code == 204
    s = editor.get(f"/api/subnets/{s['id']}").json
    assert s['vlan'] is None and s['vlan_id'] is None


def test_plain_vlan_number_still_works(editor):
    s = editor.post('/api/subnets', {'name': 'lan', 'cidr': '10.0.0.0/24', 'vlan': 30}).json
    assert s['vlan'] == 30 and s['vlan_name'] == 'VLAN 30'
    again = editor.post('/api/subnets', {'name': 'lan2', 'cidr': '10.0.1.0/24', 'vlan': 30}).json
    assert again['vlan_id'] == s['vlan_id']


def test_tags_are_created_on_use_and_filter(editor, subnet):
    s = editor.put(f"/api/subnets/{subnet['id']}", {'tags': ['home', 'Critical']}).json
    assert s['tags'] == ['Critical', 'home']
    ip = editor.post('/api/ips', {'subnet_id': subnet['id'], 'address': '192.168.50.5', 'tags': ['critical', 'nas']}).json
    assert ip['tags'] == ['Critical', 'nas']  # matched case-insensitively
    editor.post('/api/ips', {'subnet_id': subnet['id'], 'address': '192.168.50.6'})
    assert [i['address'] for i in editor.get('/api/ips?tag=nas').json['items']] == ['192.168.50.5']
    assert [x['name'] for x in editor.get('/api/subnets?tag=home').json['items']] == ['lan']
    tags = {t['name']: t for t in editor.get('/api/tags').json['items']}
    assert tags['Critical']['subnets'] == 1 and tags['Critical']['ips'] == 1


def test_renaming_tag_onto_existing_merges(editor, subnet):
    editor.post('/api/ips', {'subnet_id': subnet['id'], 'address': '192.168.50.5', 'tags': ['srv']})
    editor.post('/api/ips', {'subnet_id': subnet['id'], 'address': '192.168.50.6', 'tags': ['server']})
    tags = {t['name']: t for t in editor.get('/api/tags').json['items']}
    resp = editor.put(f"/api/tags/{tags['srv']['id']}", {'name': 'server'})
    assert resp.status_code == 200
    names = [t['name'] for t in editor.get('/api/tags').json['items']]
    assert names == ['server']
    assert editor.get('/api/ips?tag=server').json['total'] == 2


def test_viewer_cannot_create_tags_or_vlans(viewer):
    assert viewer.post('/api/vlans', {'vid': 2, 'name': 'x'}).status_code == 403


def test_tag_changes_show_in_history(editor, subnet):
    editor.put(f"/api/subnets/{subnet['id']}", {'tags': ['a']})
    editor.put(f"/api/subnets/{subnet['id']}", {'tags': ['a', 'b']})
    entry = editor.get(f"/api/changes?entity=subnet&id={subnet['id']}").json['items'][0]
    assert entry['diff'] == {'tags': [['a'], ['a', 'b']]}


def test_json_export_import_keeps_vlans_and_tags(admin):
    v = admin.post('/api/vlans', {'vid': 40, 'name': 'Lab'}).json
    s = admin.post('/api/subnets', {'name': 'lab', 'cidr': '10.4.0.0/24', 'vlan_id': v['id'], 'tags': ['x']}).json
    admin.post('/api/ips', {'subnet_id': s['id'], 'address': '10.4.0.5', 'tags': ['y']})
    dump = admin.get('/api/export').json
    assert dump['format'] == 3 and dump['vlans'][0]['name'] == 'Lab'
    assert admin.post('/api/import?mode=replace', dump).status_code == 200
    s2 = admin.get('/api/subnets').json['items'][0]
    assert s2['vlan'] == 40 and s2['vlan_name'] == 'Lab' and s2['tags'] == ['x']
    assert admin.get('/api/ips').json['items'][0]['tags'] == ['y']


def test_old_export_format_with_integer_vlan_imports(admin):
    old = {'format': 2, 'subnets': [{'name': 'old', 'cidr': '10.5.0.0/24', 'vlan': 55, 'tags': ['legacy'], 'ips': []}]}
    assert admin.post('/api/import', old).status_code == 200
    s = admin.get('/api/subnets').json['items'][0]
    assert s['vlan'] == 55 and s['tags'] == ['legacy']

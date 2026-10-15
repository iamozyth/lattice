// Dialog forms shared by several views.
import { post, put } from './api.js';
import { dialog, field, formValues, h, input, select, toast } from './dom.js';

export const STATUSES = ['in-use', 'reserved', 'dhcp', 'available', 'blocked', 'deprecated'];

function showWarnings(result) {
  for (const w of result?.warnings || []) toast(w, 'warn');
}

export function subnetDialog(subnet = null, environments = []) {
  const s = subnet || {};
  const envList = h('datalist', { id: 'env-list' },
    [...new Set(['prod', 'staging', 'dev', 'lab', 'iot', 'guest', ...environments])].map((e) => h('option', { value: e })));
  const body = h('div.grid-2', {},
    field('Name', input('name', s.name, { required: true, maxlength: 255 })),
    field('CIDR', input('cidr', s.cidr, { required: true, placeholder: '192.168.1.0/24', class: 'mono' })),
    field('Gateway', input('gateway', s.gateway, { placeholder: '192.168.1.1', class: 'mono' })),
    field('VLAN', input('vlan', s.vlan, { type: 'number', min: 1, max: 4094 })),
    field('DNS primary', input('dns_primary', s.dns_primary, { class: 'mono' })),
    field('DNS secondary', input('dns_secondary', s.dns_secondary, { class: 'mono' })),
    field('Environment', input('environment', s.environment, { list: 'env-list' })),
    field('Location', input('location', s.location)),
    h('div.wide', {}, field('Tags', input('tags', (s.tags || []).join(', '), { placeholder: 'comma separated' }))),
    h('div.wide', {}, field('Description', h('textarea', { name: 'description', rows: 2 }, s.description || ''))),
    h('div.wide', {}, field('Scheduled scans', select('scan_enabled', [
      ['', 'Automatic (whole subnet up to /20, otherwise documented IPs)'],
      ['true', 'Always sweep the whole subnet'], ['false', 'Never scan']],
    s.scan_enabled === null || s.scan_enabled === undefined ? '' : String(s.scan_enabled)))),
    envList);
  return dialog({
    title: subnet ? `Edit ${subnet.name}` : 'New subnet',
    body,
    onSubmit: async (fd) => {
      const v = formValues(fd, ['name', 'cidr', 'gateway', 'vlan', 'dns_primary', 'dns_secondary',
        'environment', 'location', 'tags', 'description', 'scan_enabled']);
      v.tags = v.tags ? v.tags.split(',').map((t) => t.trim()).filter(Boolean) : [];
      v.scan_enabled = v.scan_enabled === null ? null : v.scan_enabled === 'true';
      const result = subnet ? await put(`/api/subnets/${subnet.id}`, v) : await post('/api/subnets', v);
      showWarnings(result);
      return result;
    },
  });
}

const IP_FIELDS = ['address', 'hostname', 'fqdn', 'status', 'mac_address', 'device_type', 'manufacturer',
  'model', 'serial_number', 'owner', 'department', 'description', 'notes'];

// ip: existing record to edit, or a partial prefill ({ address, hostname, ... }) for a new one
export function ipDialog(ip = {}, { subnetId, suggest } = {}) {
  const editing = Boolean(ip.id);
  const addr = input('address', ip.address, { required: true, class: 'mono', placeholder: '192.168.1.10' });
  const next = suggest && !editing
    ? h('button', { type: 'button', onclick: async (e) => {
      e.currentTarget.disabled = true;
      try { const r = await suggest(); if (r) addr.value = r; else toast('No free address outside DHCP pools', 'warn'); } finally { e.currentTarget.disabled = false; }
    } }, 'Next free') : null;
  const body = h('div.grid-2', {},
    field('Address', h('div.row', {}, addr, next)),
    field('Status', select('status', STATUSES.map((s) => [s, s]), ip.status || 'in-use')),
    field('Hostname', input('hostname', ip.hostname)),
    field('FQDN', input('fqdn', ip.fqdn)),
    field('MAC address', input('mac_address', ip.mac_address, { class: 'mono', placeholder: 'AA:BB:CC:DD:EE:FF' })),
    field('Device type', input('device_type', ip.device_type, { placeholder: 'server, printer, AP…' })),
    field('Manufacturer', input('manufacturer', ip.manufacturer)),
    field('Model', input('model', ip.model)),
    field('Serial number', input('serial_number', ip.serial_number)),
    field('Owner', input('owner', ip.owner)),
    h('div.wide', {}, field('Description', input('description', ip.description))),
    h('div.wide', {}, field('Notes', h('textarea', { name: 'notes', rows: 2 }, ip.notes || ''))));
  addr.style.flex = '1';
  return dialog({
    title: editing ? `Edit ${ip.address}` : 'Document an address',
    wide: true,
    body,
    onSubmit: async (fd) => {
      const v = formValues(fd, IP_FIELDS);
      const result = editing
        ? await put(`/api/ips/${ip.id}`, v)
        : await post('/api/ips', { ...v, subnet_id: subnetId ?? ip.subnet_id ?? null });
      showWarnings(result);
      return result;
    },
  });
}

export function dhcpDialog(subnet, range = null) {
  const body = h('div.grid-2', {},
    field('First address', input('start', range?.start, { required: true, class: 'mono' })),
    field('Last address', input('end', range?.end, { required: true, class: 'mono' })),
    h('div.wide', {}, field('Description', input('description', range?.description, { placeholder: 'e.g. router DHCP' }))));
  return dialog({
    title: range ? 'Edit DHCP range' : `DHCP range in ${subnet.cidr}`,
    body,
    onSubmit: (fd) => {
      const v = formValues(fd, ['start', 'end', 'description']);
      return range ? put(`/api/dhcp-ranges/${range.id}`, v) : post(`/api/subnets/${subnet.id}/dhcp-ranges`, v);
    },
  });
}

export function bulkDialog(subnet) {
  const area = h('textarea.mono', { name: 'rows', rows: 10, required: true,
    placeholder: '192.168.1.10, nas, in-use\n192.168.1.11, printer\n192.168.1.12' });
  return dialog({
    title: `Bulk add to ${subnet.name}`,
    body: field('One address per line: address, hostname, status', area, 'Up to 1000 lines. Status defaults to in-use.'),
    submitLabel: 'Add',
    onSubmit: async (fd) => {
      const ips = String(fd.get('rows')).split('\n').map((l) => l.trim()).filter(Boolean).map((line) => {
        const [address, hostname, status] = line.split(/[,\t;]/).map((p) => p.trim());
        return { address, hostname: hostname || null, status: status || 'in-use' };
      });
      const r = await post('/api/ips/bulk', { subnet_id: subnet.id, ips }).catch((err) => {
        if (err.data?.errors) return err.data;
        throw err;
      });
      if (r.errors.length) {
        toast(`${r.created.length} added, ${r.errors.length} skipped: ${r.errors.slice(0, 3)
          .map((e) => `${e.address ?? '?'} (${e.error})`).join(', ')}${r.errors.length > 3 ? '…' : ''}`,
        r.created.length ? 'warn' : 'error');
      } else {
        toast(`${r.created.length} addresses added`);
      }
      return r.created.length ? r : false;
    },
  });
}

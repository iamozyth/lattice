// Dialog forms shared by several views.
import { get, post, put } from './api.js';
import { busy, dialog, field, formValues, h, input, select, toast } from './dom.js';
import { changeList } from './views/changes.js';

export const STATUSES = ['in-use', 'reserved', 'dhcp', 'available', 'blocked', 'deprecated'];

function showWarnings(result) {
  for (const w of result?.warnings || []) toast(w, 'warn');
}

// opts: environments, subnets (for the parent picker), parentId and cidr to prefill
export async function subnetDialog(subnet = null, opts = {}) {
  const s = subnet || {};
  const [{ items: vlans }, tagList] = await Promise.all([get('/api/vlans'), tagDatalist()]);
  // Pick a VLAN, or type a new number (created as "VLAN n" on save)
  const vlanSel = select('vlan_id', [['', 'None'], ...vlans.map((v) => [v.id, `${v.vid} · ${v.name}${v.site ? ` (${v.site})` : ''}`]), ['new', 'New VLAN number…']], s.vlan_id ?? '');
  const vlanNum = input('vlan', '', { type: 'number', min: 1, max: 4094, placeholder: 'e.g. 30', class: 'hidden', 'aria-label': 'New VLAN number' });
  vlanSel.addEventListener('change', () => { vlanNum.classList.toggle('hidden', vlanSel.value !== 'new'); if (vlanSel.value === 'new') vlanNum.focus(); });
  const envList = h('datalist', { id: 'env-list' },
    [...new Set(['prod', 'staging', 'dev', 'lab', 'iot', 'guest', ...(opts.environments || [])])].map((e) => h('option', { value: e })));
  const cidr = input('cidr', s.cidr || opts.cidr, { required: true, placeholder: '192.168.1.0/24', class: 'mono' });
  // New subnets can be carved out of an existing one: pick it, a size, then Next free
  let carve = null;
  if (!subnet && opts.subnets?.length) {
    const parent = select('parent', [['', 'Top level'], ...opts.subnets.map((p) => [p.id, `${'– '.repeat(p.depth || 0)}${p.name} · ${p.cidr}`])], opts.parentId ?? '');
    const size = input('size', '', { type: 'number', min: 1, max: 128, placeholder: '24', 'aria-label': 'Prefix length' });
    const next = h('button', { type: 'button', onclick: (e) => busy(e.currentTarget, async () => {
      if (!parent.value) { toast('Pick the subnet to carve from first', 'warn'); return; }
      const r = await get(`/api/subnets/${parent.value}/free-blocks?prefix=${size.value || 24}&limit=1`);
      if (r.next.length) cidr.value = r.next[0];
      else toast(`No free /${size.value || 24} left in that subnet`, 'warn');
    }) }, 'Next free');
    size.style.width = '72px';
    carve = h('div.wide', {}, field('Inside', h('div.row', {}, parent, h('span.faint', {}, '/'), size, next),
      'Optional. Addresses already documented in that range move into the new subnet.'));
    parent.style.flex = '1';
  }
  const body = h('div.grid-2', {},
    carve,
    field('Name', input('name', s.name, { required: true, maxlength: 255 })),
    field('CIDR', cidr),
    field('Gateway', input('gateway', s.gateway, { placeholder: '192.168.1.1', class: 'mono' })),
    field('VLAN', h('div.row', {}, vlanSel, vlanNum)),
    field('DNS primary', input('dns_primary', s.dns_primary, { class: 'mono' })),
    field('DNS secondary', input('dns_secondary', s.dns_secondary, { class: 'mono' })),
    field('Environment', input('environment', s.environment, { list: 'env-list' })),
    field('Location', input('location', s.location)),
    h('div.wide', {}, field('Tags', input('tags', (s.tags || []).join(', '), { placeholder: 'comma separated', list: 'tag-list' }))),
    tagList,
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
      const v = formValues(fd, ['name', 'cidr', 'gateway', 'dns_primary', 'dns_secondary',
        'environment', 'location', 'tags', 'description', 'scan_enabled']);
      v.tags = v.tags ? v.tags.split(',').map((t) => t.trim()).filter(Boolean) : [];
      if (vlanSel.value === 'new') v.vlan = vlanNum.value || null;
      else v.vlan_id = vlanSel.value || null;
      v.scan_enabled = v.scan_enabled === null ? null : v.scan_enabled === 'true';
      const result = subnet ? await put(`/api/subnets/${subnet.id}`, v) : await post('/api/subnets', v);
      showWarnings(result);
      if (result.moved) toast(`Moved ${result.moved} address${result.moved === 1 ? '' : 'es'} from ${result.inside?.name || 'the parent'}`);
      return result;
    },
  });
}

const IP_FIELDS = ['address', 'hostname', 'fqdn', 'status', 'mac_address', 'device_type', 'manufacturer',
  'model', 'serial_number', 'owner', 'department', 'description', 'notes', 'tags'];

// Existing tag names as suggestions for tag inputs
async function tagDatalist() {
  const { items } = await get('/api/tags').catch(() => ({ items: [] }));
  return h('datalist', { id: 'tag-list' }, items.map((t) => h('option', { value: t.name })));
}

export function tagPills(tags, base = '#/addresses') {
  return (tags || []).map((t) => h('a.pill', { href: `${base}?tag=${encodeURIComponent(t)}`, onclick: (e) => e.stopPropagation() }, t));
}

export function vlanDialog(vlan = null) {
  return dialog({
    title: vlan ? `Edit VLAN ${vlan.vid}` : 'New VLAN',
    body: h('div.grid-2', {},
      field('VLAN ID', input('vid', vlan?.vid, { type: 'number', min: 1, max: 4094, required: true })),
      field('Name', input('name', vlan?.name, { required: true, maxlength: 100 })),
      field('Site', input('site', vlan?.site, { placeholder: 'Optional, for the same ID at another site' })),
      h('div.wide', {}, field('Description', input('description', vlan?.description)))),
    onSubmit: (fd) => {
      const v = formValues(fd, ['vid', 'name', 'site', 'description']);
      v.site = v.site || '';
      return vlan ? put(`/api/vlans/${vlan.id}`, v) : post('/api/vlans', v);
    },
  });
}

// ip: existing record to edit, or a partial prefill ({ address, hostname, ... }) for a new one
export async function ipDialog(ip = {}, { subnetId, suggest } = {}) {
  const editing = Boolean(ip.id);
  const tagList = await tagDatalist();
  const addr = input('address', ip.address, { required: true, class: 'mono', placeholder: '192.168.1.10' });
  const next = suggest && !editing
    ? h('button', { type: 'button', onclick: (e) => busy(e.currentTarget, async () => {
      const r = await suggest();
      if (r) addr.value = r;
      else toast('No free address outside DHCP pools', 'warn');
    }) }, 'Next free') : null;
  const hasMore = ['fqdn', 'device_type', 'manufacturer', 'model', 'serial_number', 'owner', 'department', 'notes'].some((k) => ip[k]);
  const body = h('div.stack', {},
    h('div.grid-2', {},
      field('Address', h('div.row', {}, addr, next)),
      field('Status', select('status', STATUSES.map((s) => [s, s]), ip.status || 'in-use')),
      field('Hostname', input('hostname', ip.hostname)),
      field('MAC address', input('mac_address', ip.mac_address, { class: 'mono', placeholder: 'AA:BB:CC:DD:EE:FF' })),
      h('div.wide', {}, field('Description', input('description', ip.description))),
      h('div.wide', {}, field('Tags', input('tags', (ip.tags || []).join(', '), { placeholder: 'comma separated', list: 'tag-list' }))),
      tagList),
    h('details.more', { open: hasMore }, h('summary', {}, 'More details'),
      h('div.grid-2', {},
        field('FQDN', input('fqdn', ip.fqdn)),
        field('Device type', input('device_type', ip.device_type, { placeholder: 'server, printer, AP…' })),
        field('Manufacturer', input('manufacturer', ip.manufacturer)),
        field('Model', input('model', ip.model)),
        field('Serial number', input('serial_number', ip.serial_number)),
        field('Owner', input('owner', ip.owner)),
        field('Department', input('department', ip.department)),
        h('div.wide', {}, field('Notes', h('textarea', { name: 'notes', rows: 2 }, ip.notes || ''))))),
    editing ? historySection(ip.id) : null);
  addr.style.flex = '1';
  return dialog({
    title: editing ? `Edit ${ip.address}` : 'Document an address',
    body,
    onSubmit: async (fd) => {
      const v = formValues(fd, IP_FIELDS);
      v.tags = v.tags ? v.tags.split(',').map((t) => t.trim()).filter(Boolean) : [];
      const result = editing
        ? await put(`/api/ips/${ip.id}`, v)
        : await post('/api/ips', { ...v, subnet_id: subnetId ?? ip.subnet_id ?? null });
      showWarnings(result);
      return result;
    },
  });
}

// Collapsed by default; loads the address's changes when opened
function historySection(ipId) {
  const list = h('div', {}, h('p.note', {}, 'Loading…'));
  const box = h('details.more', {}, h('summary', {}, 'History'), list);
  box.addEventListener('toggle', async () => {
    if (!box.open || box.dataset.loaded) return;
    box.dataset.loaded = '1';
    const { items } = await get(`/api/changes?entity=ip&id=${ipId}&limit=20`);
    list.replaceChildren(items.length ? changeList(items, { compact: true }) : h('p.note', {}, 'No changes recorded.'));
  });
  return box;
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

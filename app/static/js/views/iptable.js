// Paged address table, used by the subnet page and the Addresses page.
import { del, get } from '../api.js';
import { ago, busy, confirmDialog, empty, h, icon, mount, status, toast } from '../dom.js';
import { ipDialog, STATUSES } from '../forms.js';
import { can } from '../state.js';

export function ipTable({ subnetId = null, search = '', showSubnet = false, onChange = () => {}, suggest } = {}) {
  const opts = { page: 1, status: '', search };
  const body = h('div');
  const pager = h('div.pager');
  const root = h('div', {}, body, pager);

  async function load() {
    const q = new URLSearchParams({ page: opts.page, per_page: 100 });
    if (subnetId) q.set('subnet_id', subnetId);
    if (opts.status) q.set('status', opts.status);
    if (opts.search) q.set('search', opts.search);
    const data = await get(`/api/ips?${q}`);
    draw(data);
    return data;
  }

  async function edit(ip) {
    if (await ipDialog(ip)) { await load(); onChange(); }
  }

  async function remove(ip, button) {
    if (!(await confirmDialog(`Delete ${ip.address}?`, 'The record and its notes are removed. The device itself is not affected.'))) return;
    await busy(button, async () => {
      await del(`/api/ips/${ip.id}`);
      toast(`${ip.address} deleted`);
      await load();
      onChange();
    });
  }

  function draw(data) {
    if (!data.items.length) {
      const filtered = opts.status || opts.search;
      mount(body, empty(filtered ? 'No matching addresses' : 'No addresses documented',
        filtered ? 'Try a different filter.' : subnetId ? 'Add one, bulk add, or scan the subnet to find hosts.' : null));
      mount(pager);
      return;
    }
    const rows = data.items.map((ip) => h('tr', {},
      h('td.mono', {}, ip.address),
      h('td', {}, ip.hostname || h('span.faint', {}, '—'), ip.description ? h('span.sub', { title: ip.description }, ip.description) : null),
      showSubnet ? h('td.opt', {}, h('a', { href: `#/subnets/${ip.subnet_id}` }, ip.subnet_name)) : null,
      h('td', {}, status(ip.status)),
      h('td.mono.muted.opt', {}, ip.mac_address || ''),
      h('td.muted.opt', {}, ip.device_type || ip.manufacturer || ''),
      h('td.muted.opt', { title: ip.last_seen || 'never seen by a scan' }, ip.last_seen ? ago(ip.last_seen) : '—'),
      h('td.actions', {}, can('editor') ? [
        h('button.ghost.icon.hover', { 'aria-label': `Edit ${ip.address}`, onclick: () => edit(ip) }, icon('edit')),
        h('button.ghost.icon.danger.hover', { 'aria-label': `Delete ${ip.address}`, onclick: (e) => remove(ip, e.currentTarget) }, icon('trash')),
      ] : null)));
    mount(body, h('div.table-wrap', {}, h('table', {},
      h('thead', {}, h('tr', {}, h('th', {}, 'Address'), h('th', {}, 'Hostname'), showSubnet ? h('th.opt', {}, 'Subnet') : null,
        h('th', {}, 'Status'), h('th.opt', {}, 'MAC'), h('th.opt', {}, 'Device'), h('th.opt', {}, 'Last seen'), h('th', {}, h('span.sr-only', {}, 'Actions')))),
      h('tbody', {}, rows))));
    mount(pager, h('span', {}, `${data.total} address${data.total === 1 ? '' : 'es'}`), h('span.grow'),
      data.pages > 1 ? [
        h('button', { disabled: data.page <= 1, onclick: () => { opts.page -= 1; load(); } }, 'Previous'),
        h('span.mono', {}, `${data.page} / ${data.pages}`),
        h('button', { disabled: data.page >= data.pages, onclick: () => { opts.page += 1; load(); } }, 'Next'),
      ] : null);
  }

  const statusFilter = h('select', { 'aria-label': 'Status', onchange: (e) => { opts.status = e.target.value; opts.page = 1; load(); } },
    h('option', { value: '' }, 'Any status'), STATUSES.map((s) => h('option', { value: s }, s)));

  async function add(prefill = {}) {
    if (await ipDialog(prefill, { subnetId, suggest })) { await load(); onChange(); }
  }

  return {
    el: root,
    statusFilter,
    load,
    add,
    edit,
    setSearch(value) { opts.search = value; opts.page = 1; return load(); },
  };
}

// Paged address table with selection for bulk edits; used by the subnet page and the Addresses page.
import { del, get, post } from '../api.js';
import { ago, busy, confirmDialog, dialog, empty, field, h, icon, input, mount, select, status, toast } from '../dom.js';
import { ipDialog, STATUSES, tagPills } from '../forms.js';
import { can } from '../state.js';

export function ipTable({ subnetId = null, search = '', tag = '', showSubnet = false, onChange = () => {}, suggest } = {}) {
  const opts = { page: 1, status: '', search, tag };
  const selected = new Set();
  const bar = h('div.selection-bar.hidden');
  const body = h('div');
  const pager = h('div.pager');
  const root = h('div', {}, bar, body, pager);
  let current = { items: [] };

  function filters() {
    const q = new URLSearchParams();
    if (subnetId) q.set('subnet_id', subnetId);
    if (opts.status) q.set('status', opts.status);
    if (opts.search) q.set('search', opts.search);
    if (opts.tag) q.set('tag', opts.tag);
    return q;
  }

  async function load() {
    const q = filters();
    q.set('page', opts.page);
    q.set('per_page', 100);
    current = await get(`/api/ips?${q}`);
    for (const id of [...selected]) if (!current.items.some((ip) => ip.id === id)) selected.delete(id);
    draw(current);
    return current;
  }

  async function changed() { selected.clear(); await load(); onChange(); }

  async function edit(ip) {
    if (await ipDialog(ip)) await changed();
  }

  async function remove(ip, button) {
    if (!(await confirmDialog(`Delete ${ip.address}?`, 'The record and its notes are removed. The device itself is not affected.'))) return;
    await busy(button, async () => {
      await del(`/api/ips/${ip.id}`);
      toast(`${ip.address} deleted`);
      await changed();
    });
  }

  // ---------- bulk actions on the selection ----------
  async function bulk(body, message) {
    const r = await post('/api/ips/bulk-update', { ids: [...selected], ...body });
    toast(message(r.updated));
    await changed();
  }

  function askOne(title, label, name, extra = {}) {
    return dialog({ title, body: field(label, input(name, '', { required: true, ...extra })), submitLabel: 'Apply',
      onSubmit: (fd) => String(fd.get(name)).trim() });
  }

  function drawBar() {
    const n = selected.size;
    bar.classList.toggle('hidden', !n);
    if (!n) return;
    const setStatus = select('bulk-status', [['', 'Set status…'], ...STATUSES.map((s) => [s, s])], '');
    setStatus.addEventListener('change', () => busy(setStatus, () => bulk({ set: { status: setStatus.value } },
      (u) => `${u} address${u === 1 ? '' : 'es'} set to ${setStatus.value}`)));
    mount(bar,
      h('strong', {}, `${n} selected`),
      setStatus,
      h('button.sm', { onclick: async () => {
        const owner = await askOne(`Owner of ${n} addresses`, 'Owner', 'owner');
        if (owner) await busy(null, () => bulk({ set: { owner } }, (u) => `Owner set on ${u}`));
      } }, 'Set owner'),
      h('button.sm', { onclick: async () => {
        const t = await askOne(`Tag ${n} addresses`, 'Tags to add', 'tags', { placeholder: 'comma separated', list: 'tag-list' });
        if (t) await busy(null, () => bulk({ add_tags: t.split(',').map((x) => x.trim()).filter(Boolean) }, (u) => `Tagged ${u}`));
      } }, 'Add tag'),
      h('button.sm', { onclick: async () => {
        const t = await askOne(`Remove tags from ${n} addresses`, 'Tags to remove', 'tags', { placeholder: 'comma separated' });
        if (t) await busy(null, () => bulk({ remove_tags: t.split(',').map((x) => x.trim()).filter(Boolean) }, (u) => `Updated ${u}`));
      } }, 'Remove tag'),
      h('button.sm.danger', { onclick: async () => {
        if (!(await confirmDialog(`Delete ${n} addresses?`, 'Their records and notes are removed. The devices are not affected.'))) return;
        await busy(null, async () => {
          const r = await post('/api/ips/bulk-delete', { ids: [...selected] });
          toast(`${r.deleted} address${r.deleted === 1 ? '' : 'es'} deleted`);
          await changed();
        });
      } }, 'Delete'),
      h('button.ghost.sm', { onclick: () => { selected.clear(); draw(current); } }, 'Clear'));
  }

  function draw(data) {
    drawBar();
    if (!data.items.length) {
      const filtered = opts.status || opts.search || opts.tag;
      mount(body, empty(filtered ? 'No matching addresses' : 'No addresses documented',
        filtered ? 'Try a different filter.' : subnetId ? 'Add one, bulk add, or scan the subnet to find hosts.' : null));
      mount(pager);
      return;
    }
    const editor = can('editor');
    const toggle = (ip, box) => {
      if (box.checked) selected.add(ip.id); else selected.delete(ip.id);
      box.closest('tr').classList.toggle('selected', box.checked);
      drawBar();
      syncAll();
    };
    const all = h('input', { type: 'checkbox', 'aria-label': 'Select all on this page', onchange: (e) => {
      for (const ip of data.items) { if (e.target.checked) selected.add(ip.id); else selected.delete(ip.id); }
      draw(data);
    } });
    function syncAll() {
      const n = data.items.filter((ip) => selected.has(ip.id)).length;
      all.checked = n === data.items.length;
      all.indeterminate = n > 0 && n < data.items.length;
    }
    const rows = data.items.map((ip) => {
      const box = h('input', { type: 'checkbox', checked: selected.has(ip.id), 'aria-label': `Select ${ip.address}` });
      box.addEventListener('change', () => toggle(ip, box));
      return h('tr', { class: selected.has(ip.id) ? 'selected' : '' },
        editor ? h('td.check-cell', {}, box) : null,
        h('td.mono', {}, ip.address),
        h('td', {}, ip.hostname || h('span.faint', {}, '—'), ip.tags?.length ? [' ', tagPills(ip.tags)] : null,
          ip.description ? h('span.sub', { title: ip.description }, ip.description) : null),
        showSubnet ? h('td.opt', {}, h('a', { href: `#/subnets/${ip.subnet_id}` }, ip.subnet_name)) : null,
        h('td', {}, status(ip.status)),
        h('td.mono.muted.opt', {}, ip.mac_address || ''),
        h('td.muted.opt', {}, ip.device_type || ip.manufacturer || ''),
        h('td.muted.opt', { title: ip.last_seen || 'never seen by a scan' }, ip.last_seen ? ago(ip.last_seen) : '—'),
        h('td.actions', {}, editor ? [
          h('button.ghost.icon.hover', { 'aria-label': `Edit ${ip.address}`, onclick: () => edit(ip) }, icon('edit')),
          h('button.ghost.icon.danger.hover', { 'aria-label': `Delete ${ip.address}`, onclick: (e) => remove(ip, e.currentTarget) }, icon('delete')),
        ] : null));
    });
    mount(body, h('div.table-wrap', {}, h('table', {},
      h('thead', {}, h('tr', {}, editor ? h('th.check-cell', {}, all) : null, h('th', {}, 'Address'), h('th', {}, 'Hostname'),
        showSubnet ? h('th.opt', {}, 'Subnet') : null, h('th', {}, 'Status'), h('th.opt', {}, 'MAC'), h('th.opt', {}, 'Device'),
        h('th.opt', {}, 'Last seen'), h('th', {}, h('span.sr-only', {}, 'Actions')))),
      h('tbody', {}, rows))));
    syncAll();
    mount(pager, h('span', {}, `${data.total} address${data.total === 1 ? '' : 'es'}`), h('span.grow'),
      data.pages > 1 ? [
        h('button.sm', { disabled: data.page <= 1, onclick: () => { opts.page -= 1; load(); } }, 'Previous'),
        h('span.mono', {}, `${data.page} / ${data.pages}`),
        h('button.sm', { disabled: data.page >= data.pages, onclick: () => { opts.page += 1; load(); } }, 'Next'),
      ] : null);
  }

  const statusFilter = h('select', { 'aria-label': 'Status', onchange: (e) => { opts.status = e.target.value; opts.page = 1; load(); } },
    h('option', { value: '' }, 'Any status'), STATUSES.map((s) => h('option', { value: s }, s)));

  async function add(prefill = {}) {
    if (await ipDialog(prefill, { subnetId, suggest })) await changed();
  }

  return {
    el: root,
    statusFilter,
    load,
    add,
    edit,
    exportUrl: () => `/api/export.csv?type=ips&${filters()}`,
    setSearch(value) { opts.search = value; opts.page = 1; return load(); },
  };
}

import { get } from '../api.js';
import { $, h, mount, pageHead, status } from '../dom.js';
import { can } from '../state.js';
import { ipTable } from './iptable.js';

const IP_RE = /^(\d{1,3}(\.\d{1,3}){3}|[0-9a-f:]*:[0-9a-f:.]+)$/i;

export async function render(root, _params, query) {
  const search = query.get('search') || '';
  const box = $('#search');
  if (box.value !== search) box.value = search;

  const table = ipTable({ search, showSubnet: true });
  const lookup = h('div');
  const tablePanel = h('section.panel');

  mount(root,
    pageHead(search ? `Results for “${search}”` : 'Addresses', null,
      can('editor') ? h('button.primary', { onclick: () => table.add() }, 'Add address') : null),
    lookup, tablePanel);
  mount(tablePanel, h('div.panel-head', {}, h('h3', {}, search ? 'Matches' : 'All subnets'),
    h('div.actions', {}, table.statusFilter)), table.el);

  const [data] = await Promise.all([table.load(), IP_RE.test(search) ? showLookup(search, lookup, table) : null]);
  if (IP_RE.test(search) && !data.total && lookup.childElementCount) tablePanel.classList.add('hidden');
}

async function showLookup(address, target, table) {
  let r;
  try { r = await get(`/api/lookup/${encodeURIComponent(address)}`); } catch { return; }
  const text = !r.subnet
    ? [h('span.mono', {}, r.address), ' is not inside any subnet.']
    : r.ip
      ? [h('span.mono', {}, r.address), ' is documented in ', h('a', { href: `#/subnets/${r.subnet.id}` }, r.subnet.name), ' ', status(r.ip.status)]
      : [h('span.mono', {}, r.address), ' belongs to ', h('a', { href: `#/subnets/${r.subnet.id}` }, r.subnet.name),
        ` (${r.subnet.cidr}) and is not documented. `,
        can('editor') ? h('button', { onclick: () => table.add({ address: r.address, subnet_id: r.subnet.id }) }, 'Document it') : null];
  mount(target, h('div.panel.pad.lookup', {}, h('div.row', {}, text)));
}

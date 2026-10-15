import { get } from '../api.js';
import { debounce, h, mount, pageHead, status } from '../dom.js';
import { can } from '../state.js';
import { csvImportDialog } from './csvimport.js';
import { ipTable } from './iptable.js';

const IP_RE = /^(\d{1,3}(\.\d{1,3}){3}|[0-9a-f:]*:[0-9a-f:.]+)$/i;

export async function render(root, _params, query) {
  const search = query.get('search') || '';
  const box = h('input', { type: 'search', value: search, placeholder: 'Filter by address, hostname, MAC, owner or tag',
    'aria-label': 'Filter addresses', oninput: debounce(() => {
      const q = box.value.trim();
      history.replaceState(null, '', q ? `#/addresses?search=${encodeURIComponent(q)}` : '#/addresses');
      table.setSearch(q);
    }, 250) });
  box.style.flex = '1';

  const tag = query.get('tag') || '';
  const table = ipTable({ search, tag, showSubnet: true });
  const lookup = h('div');
  const tablePanel = h('section.panel');

  mount(root,
    pageHead(null, tag ? `Addresses tagged “${tag}”` : search ? `Results for “${search}”` : 'Every documented address.',
      h('a.btn', { href: table.exportUrl(), download: '' }, 'Export CSV'),
      can('editor') ? h('button', { onclick: async () => { if (await csvImportDialog('ips')) table.load(); } }, 'Import CSV…') : null,
      can('editor') ? h('button.primary', { onclick: () => table.add() }, 'Add address') : null),
    lookup, tablePanel);
  mount(tablePanel, h('div.panel-head', {}, box, h('div.actions', {}, table.statusFilter)), table.el);

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

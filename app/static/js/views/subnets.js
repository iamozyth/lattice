import { get } from '../api.js';
import { debounce, empty, h, icon, mount, pageHead, utilBar } from '../dom.js';
import { subnetDialog } from '../forms.js';
import { can } from '../state.js';
import { csvImportDialog } from './csvimport.js';

// Collapsed branches are a per-browser convenience
const KEY = 'lattice.collapsed';
const load = () => { try { return new Set(JSON.parse(localStorage.getItem(KEY) || '[]')); } catch { return new Set(); } };
const store = (set) => { try { localStorage.setItem(KEY, JSON.stringify([...set])); } catch { /* private mode */ } };

export async function render(root, _params, query) {
  const tag = query.get('tag') || '';
  const [stats, list] = await Promise.all([get('/api/stats'), get(`/api/subnets${tag ? `?tag=${encodeURIComponent(tag)}` : ''}`)]);
  const body = h('div');
  const collapsed = load();
  let text = '';

  function visible(items) {
    if (text) {
      const t = text.toLowerCase();
      return items.filter((s) => [s.name, s.cidr, s.location, s.environment, s.description,
        s.vlan && `vlan ${s.vlan}`, ...s.tags].some((v) => String(v || '').toLowerCase().includes(t)));
    }
    // Hide everything below a collapsed subnet (the list is in tree order)
    const out = [];
    let hideBelow = null;
    for (const s of items) {
      if (hideBelow !== null && s.depth > hideBelow) continue;
      hideBelow = collapsed.has(s.id) && s.children ? s.depth : null;
      out.push(s);
    }
    return out;
  }

  function toggle(e, s) {
    e.stopPropagation();
    if (collapsed.has(s.id)) collapsed.delete(s.id); else collapsed.add(s.id);
    store(collapsed);
    draw();
  }

  function nameCell(s) {
    const open = !collapsed.has(s.id);
    const twisty = s.children && !text
      ? h('button.twisty', { type: 'button', class: open ? 'open' : '', 'aria-expanded': String(open),
        'aria-label': `${open ? 'Collapse' : 'Expand'} ${s.name}`, onclick: (e) => toggle(e, s) }, icon('chev', 14))
      : h('span.twisty-space');
    return h('td', {}, h('span.tree', { class: text ? '' : `d${Math.min(s.depth, 6)}` },
      twisty,
      h('span', {}, h('a', { href: `#/subnets/${s.id}` }, s.name),
        s.children && !open ? h('span.faint', {}, ` · ${s.children} inside`) : null,
        s.location ? h('span.sub', {}, s.location) : null)));
  }

  function draw() {
    const items = visible(list.items);
    if (!list.items.length) {
      mount(body, empty('No subnets yet', can('editor') ? 'Add the networks you run with New subnet.' : 'An editor has to add subnets first.'));
      return;
    }
    if (!items.length) {
      mount(body, empty('No matches', `Nothing matches “${text}”.`));
      return;
    }
    mount(body, h('div.table-wrap', {}, h('table', {},
      h('thead', {}, h('tr', {}, h('th', {}, 'Name'), h('th', {}, 'Network'), h('th.opt', {}, 'VLAN'), h('th.opt', {}, 'Environment'), h('th', {}, 'Used'), h('th.opt', {}, 'Utilization'))),
      h('tbody', {}, items.map((s) => h('tr.link', { onclick: () => { location.hash = `#/subnets/${s.id}`; } },
        nameCell(s),
        h('td.mono', {}, s.cidr),
        h('td.mono.muted.opt', {}, s.vlan ?? ''),
        h('td.muted.opt', {}, s.environment || ''),
        s.children
          ? h('td.muted', {}, `${s.children} subnet${s.children === 1 ? '' : 's'}`)
          : h('td.mono', {}, s.used_ips, s.dhcp_ranges.length ? h('span.faint', {}, ' · dhcp') : null),
        // Containers show how much of their range is allocated to subnets
        h('td.opt', { title: s.children ? 'Allocated to subnets' : 'Addresses in use' },
          s.children ? utilBar(s.allocated) : s.version === 4 ? utilBar(s.utilization) : h('span.faint', {}, '—'))))))));
  }

  async function create() {
    const s = await subnetDialog(null, { environments: list.environments, subnets: list.items });
    if (s) location.hash = `#/subnets/${s.id}`;
  }

  const summary = tag ? `Subnets tagged “${tag}”` : list.items.length
    ? [`${stats.subnets} subnets`, `${stats.ips} addresses`,
      stats.undocumented ? `${stats.undocumented} undocumented` : null].filter(Boolean).join(' · ')
    : null;
  const filter = list.items.length > 5
    ? h('input', { type: 'search', placeholder: 'Filter subnets', 'aria-label': 'Filter subnets',
      oninput: debounce((e) => { text = e.target.value.trim(); draw(); }, 120) })
    : null;

  mount(root,
    pageHead(null, summary,
      h('a.btn', { href: `/api/export.csv?type=subnets${tag ? `&tag=${encodeURIComponent(tag)}` : ''}`, download: '' }, 'Export CSV'),
      can('editor') ? h('button', { onclick: async () => { if (await csvImportDialog('subnets')) location.reload(); } }, 'Import CSV…') : null,
      can('editor') ? h('button.primary', { onclick: create }, 'New subnet') : null),
    h('section.panel', {}, filter ? h('div.panel-head', {}, filter) : null, body));
  draw();
}

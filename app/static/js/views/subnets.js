import { get } from '../api.js';
import { debounce, empty, h, mount, pageHead, utilBar } from '../dom.js';
import { subnetDialog } from '../forms.js';
import { can } from '../state.js';

export async function render(root) {
  const [stats, list] = await Promise.all([get('/api/stats'), get('/api/subnets')]);
  const body = h('div');
  let text = '';

  function draw() {
    const t = text.toLowerCase();
    const items = list.items.filter((s) => !t || [s.name, s.cidr, s.location, s.environment, s.description,
      s.vlan && `vlan ${s.vlan}`, ...s.tags].some((v) => String(v || '').toLowerCase().includes(t)));
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
        h('td', {}, h('a', { href: `#/subnets/${s.id}` }, s.name), s.location ? h('span.sub', {}, s.location) : null),
        h('td.mono', {}, s.cidr),
        h('td.mono.muted.opt', {}, s.vlan ?? ''),
        h('td.muted.opt', {}, s.environment || ''),
        h('td.mono', {}, s.used_ips, s.dhcp_ranges.length ? h('span.faint', {}, ' · dhcp') : null),
        h('td.opt', {}, s.version === 4 ? utilBar(s.utilization) : h('span.faint', {}, '—'))))))));
  }

  async function create() {
    const s = await subnetDialog(null, list.environments);
    if (s) location.hash = `#/subnets/${s.id}`;
  }

  const summary = list.items.length
    ? [`${stats.subnets} subnets`, `${stats.ips} addresses`,
      stats.undocumented ? `${stats.undocumented} undocumented` : null].filter(Boolean).join(' · ')
    : null;
  const filter = list.items.length > 5
    ? h('input', { type: 'search', placeholder: 'Filter', 'aria-label': 'Filter subnets',
      oninput: debounce((e) => { text = e.target.value.trim(); draw(); }, 120) })
    : null;

  mount(root,
    pageHead('Subnets', summary, can('editor') ? h('button.primary', { onclick: create }, 'New subnet') : null),
    h('section.panel', {}, filter ? h('div.panel-head', {}, filter) : null, body));
  draw();
}

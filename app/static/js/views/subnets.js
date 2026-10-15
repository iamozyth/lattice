import { get } from '../api.js';
import { debounce, empty, h, icon, mount, utilBar } from '../dom.js';
import { subnetDialog } from '../forms.js';
import { can } from '../state.js';

export async function render(root) {
  const [stats, list] = await Promise.all([get('/api/stats'), get('/api/subnets')]);
  let filter = { text: '', env: '' };

  const grid = h('div.subnets');
  const draw = () => {
    const t = filter.text.toLowerCase();
    const items = list.items.filter((s) => (!filter.env || s.environment === filter.env)
      && (!t || [s.name, s.cidr, s.location, s.description, String(s.vlan ?? ''), ...s.tags]
        .some((v) => (v || '').toLowerCase().includes(t))));
    if (!list.items.length) {
      mount(grid, h('div.panel', {}, empty('No subnets yet',
        'Add the networks you run, then document addresses inside them.',
        can('editor') ? h('button.primary', { onclick: create }, icon('plus'), 'New subnet') : null)));
      return;
    }
    if (!items.length) {
      mount(grid, h('div.panel', {}, empty('No matches', 'Nothing matches this filter.')));
      return;
    }
    mount(grid, items.map(card));
  };

  async function create() {
    const s = await subnetDialog(null, list.environments);
    if (s) location.hash = `#/subnets/${s.id}`;
  }

  const env = h('select', { 'aria-label': 'Environment', onchange: (e) => { filter.env = e.target.value; draw(); } },
    h('option', { value: '' }, 'All environments'), list.environments.map((e) => h('option', { value: e }, e)));
  const text = h('input', { type: 'search', placeholder: 'Filter subnets', 'aria-label': 'Filter subnets',
    oninput: debounce((e) => { filter.text = e.target.value.trim(); draw(); }, 150) });

  mount(root,
    h('div.page-head', {}, h('h1', {}, 'Subnets'),
      h('div.actions', {}, can('editor') ? h('button.primary', { onclick: create }, icon('plus'), 'New subnet') : null)),
    h('div.stats', {},
      stat('Subnets', stats.subnets),
      stat('Documented', stats.ips),
      stat('IPv4 used', `${stats.ipv4_used} / ${stats.ipv4_capacity}`),
      stat('Utilization', `${stats.utilization}%`),
      h('a', { href: '#/drift', class: 'stat-link' }, stat('Undocumented', stats.undocumented, stats.undocumented ? 'warn-text' : ''))),
    list.items.length > 3 ? h('div.filters', {}, text, list.environments.length ? env : null) : null,
    grid);
  draw();
}

function stat(k, v, cls = '') {
  return h('div', {}, h('div.k', {}, k), h('div.v', { class: cls }, v));
}

function card(s) {
  return h('a.panel.subnet-card', { href: `#/subnets/${s.id}` },
    h('div.top', {}, h('span.name', {}, s.name), h('span.mono.muted', {}, s.cidr)),
    utilBar(s.utilization),
    h('div.foot', {},
      h('span.mono', {}, `${s.used_ips} used`),
      s.vlan ? h('span', {}, `VLAN ${s.vlan}`) : null,
      s.environment ? h('span', {}, s.environment) : null,
      s.location ? h('span', {}, s.location) : null,
      s.dhcp_ranges.length ? h('span', {}, 'DHCP') : null));
}

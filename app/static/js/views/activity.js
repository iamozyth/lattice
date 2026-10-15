import { get } from '../api.js';
import { debounce, empty, h, mount, pageHead, select } from '../dom.js';
import { changeRows } from './changes.js';

const ENTITIES = [['', 'Everything'], ['subnet', 'Subnets'], ['ip', 'Addresses'], ['dhcp_range', 'DHCP ranges'],
  ['vlan', 'VLANs'], ['tag', 'Tags'], ['user', 'Users'], ['connector', 'Connectors'], ['setting', 'Settings']];

export async function render(root, _params, query) {
  const filters = { entity: query.get('entity') || '', q: '', user: query.get('user') || '', subnet_id: query.get('subnet_id') || '' };
  const list = h('ul.changes');
  const more = h('button.sm', { onclick: () => load(false) }, 'Load older');
  const footer = h('div.pager', {}, h('span.grow'), more);
  let next = null;

  async function load(reset = true) {
    const params = new URLSearchParams({ limit: 50 });
    for (const [k, v] of Object.entries(filters)) if (v) params.set(k, v);
    if (!reset && next) params.set('before', next);
    const data = await get(`/api/changes?${params}`);
    next = data.next;
    if (reset) list.replaceChildren();
    list.append(...changeRows(data.items));
    if (!list.childElementCount) mount(list, h('li', {}, empty('Nothing recorded yet', 'Changes to subnets, addresses and settings show up here.')));
    footer.classList.toggle('hidden', !next);
  }

  const entity = select('entity', ENTITIES, filters.entity);
  entity.addEventListener('change', () => { filters.entity = entity.value; load(); });
  const search = h('input', { type: 'search', placeholder: 'Filter by name or address', 'aria-label': 'Filter activity',
    oninput: debounce((e) => { filters.q = e.target.value.trim(); load(); }, 250) });

  mount(root,
    pageHead(null, filters.subnet_id ? 'Changes in one subnet.' : 'Every change to subnets, addresses and settings, newest first.'),
    h('section.panel', {}, h('div.panel-head', {}, entity, search), list, footer));
  await load();
}

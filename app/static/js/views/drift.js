import { get, post } from '../api.js';
import { ago, busy, empty, h, icon, mount, pageHead, toast } from '../dom.js';
import { ipDialog } from '../forms.js';
import { refreshDriftCount } from '../main.js';
import { can } from '../state.js';

const CONFLICT_TEXT = {
  duplicate_mac: (c) => `MAC ${c.value} is documented on ${c.ips.length} addresses`,
  duplicate_hostname: (c) => `Hostname “${c.value}” is used by ${c.ips.length} addresses`,
  mac_mismatch: (c) => `${c.value} is documented as ${c.documented} but answered as ${c.seen}`,
  static_in_pool: (c) => `${c.value} is a static address inside a DHCP pool`,
};

export async function render(root) {
  const data = await get('/api/drift');
  const tabs = [
    ['undocumented', 'Undocumented', data.counts.undocumented],
    ['offline', 'Offline', data.counts.offline],
    ['conflicts', 'Conflicts', data.counts.conflicts],
  ];
  let current = tabs.find((t) => t[2])?.[0] || 'undocumented';
  const body = h('div');
  const seg = h('div.tabs', { role: 'tablist' });

  function draw() {
    mount(seg, tabs.map(([key, label, n]) => h('button', { type: 'button', role: 'tab',
      'aria-selected': String(key === current), onclick: () => { current = key; draw(); } }, label, h('span.n', {}, n))));
    if (current === 'undocumented') drawUndocumented();
    if (current === 'offline') drawOffline();
    if (current === 'conflicts') drawConflicts();
  }

  function drawUndocumented() {
    if (!data.undocumented.length) {
      mount(body, empty('Nothing undocumented', 'Every host seen by scans and connectors is documented or dismissed.'));
      return;
    }
    mount(body, h('div.table-wrap', {}, h('table', {},
      h('thead', {}, h('tr', {}, h('th', {}, 'Address'), h('th', {}, 'Hostname'), h('th.opt', {}, 'MAC'), h('th.opt', {}, 'Subnet'), h('th.opt', {}, 'Last seen'), h('th.opt', {}, 'Source'), h('th', {}, h('span.sr-only', {}, 'Actions')))),
      h('tbody', {}, data.undocumented.map((d) => h('tr', {},
        h('td.mono', {}, d.address),
        h('td', {}, d.hostname || h('span.faint', {}, '—'), d.vendor ? h('span.sub', { class: 'mobile-only' }, d.vendor) : null),
        h('td.mono.muted.opt', {}, d.mac_address || '', d.vendor ? h('span.sub', {}, d.vendor) : null),
        h('td.opt', {}, h('a', { href: `#/subnets/${d.subnet_id}` }, d.subnet_name)),
        h('td.muted.opt', {}, ago(d.last_seen)),
        h('td.muted.opt', {}, d.source),
        h('td.actions', {}, can('editor') ? [
          h('button', { onclick: async () => {
            const saved = await ipDialog({ address: d.address, hostname: d.hostname, mac_address: d.mac_address,
              manufacturer: d.vendor, status: 'in-use', subnet_id: d.subnet_id });
            if (saved) reload();
          } }, 'Document'),
          h('button.ghost.icon', { 'aria-label': `Dismiss ${d.address}`, title: 'Dismiss', onclick: (e) => busy(e.currentTarget, async () => {
            await post(`/api/discoveries/${d.id}/ignore`, { ignored: true });
            toast(`${d.address} dismissed`);
            reload();
          }) }, icon('x'))] : null)))))));
  }

  function drawOffline() {
    if (!data.offline.length) {
      mount(body, empty('Nothing offline', `Every in-use address answered a scan in the last ${data.stale_days} days.`));
      return;
    }
    mount(body, h('div.pad.muted', {}, `In-use addresses that haven't answered for ${data.stale_days} days. Change their status or remove them if they're gone.`),
      h('div.table-wrap', {}, h('table', {},
        h('thead', {}, h('tr', {}, ['Address', 'Hostname', 'Subnet', 'Last seen'].map((t) => h('th', {}, t)))),
        h('tbody', {}, data.offline.map((ip) => h('tr', {},
          h('td.mono', {}, ip.address), h('td', {}, ip.hostname || h('span.faint', {}, '—')),
          h('td', {}, h('a', { href: `#/subnets/${ip.subnet_id}` }, ip.subnet_name)),
          h('td.muted', {}, ago(ip.last_seen))))))));
  }

  function drawConflicts() {
    if (!data.conflicts.length) {
      mount(body, empty('No conflicts', 'No duplicate MACs or hostnames, no MAC mismatches, no static addresses in DHCP pools.'));
      return;
    }
    mount(body, h('div.table-wrap', {}, h('table', {}, h('tbody', {}, data.conflicts.map((c) => h('tr', {},
      h('td', {}, h('div', {}, CONFLICT_TEXT[c.type](c)),
        h('div.faint', {}, c.ips.map((ip, i) => [i ? ', ' : '', h('a', { href: `#/subnets/${ip.subnet_id}` }, `${ip.address}${ip.hostname ? ` (${ip.hostname})` : ''}`)])))))))));
  }

  async function reload() {
    Object.assign(data, await get('/api/drift'));
    tabs[0][2] = data.counts.undocumented;
    tabs[1][2] = data.counts.offline;
    tabs[2][2] = data.counts.conflicts;
    draw();
    refreshDriftCount();
  }

  mount(root,
    pageHead(null, 'Where the network and your documentation disagree.'),
    h('section.panel', {}, h('div.panel-head', {}, seg), body));
  draw();
}

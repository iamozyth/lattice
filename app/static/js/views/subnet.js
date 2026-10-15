import { del, get, post } from '../api.js';
import { ago, busy, confirmDialog, h, icon, mount, toast, utilBar } from '../dom.js';
import { bulkDialog, dhcpDialog, subnetDialog } from '../forms.js';
import { refreshDriftCount } from '../main.js';
import { can } from '../state.js';
import { ipTable } from './iptable.js';

const LEGEND = [
  ['in-use', 'In use'], ['reserved', 'Reserved'], ['dhcp', 'DHCP lease'], ['gateway', 'Gateway'],
  ['undocumented', 'Seen, not documented'], ['free', 'Free'], ['free pool', 'DHCP pool'],
];

export async function render(root, [id]) {
  let subnet = await get(`/api/subnets/${id}`);
  let pollTimer = null;

  const suggest = async () => (await get(`/api/subnets/${id}/free?limit=1`)).next;
  const table = ipTable({ subnetId: id, onChange: () => refresh(), suggest });

  const mapPanel = h('section.panel');
  const infoPanel = h('section.panel');
  const dhcpPanel = h('section.panel');
  const scanPanel = h('section.panel');
  const head = h('div.page-head');

  async function refresh() {
    subnet = await get(`/api/subnets/${id}`);
    drawHead();
    drawInfo();
    drawDhcp();
    await drawMap();
  }

  function drawHead() {
    mount(head,
      h('div', {}, h('a.back', { href: '#/subnets' }, '← Subnets'),
        h('div.row', {}, h('h1', {}, subnet.name), h('span.sub', {}, subnet.cidr),
          subnet.vlan ? h('span.tag', {}, `VLAN ${subnet.vlan}`) : null,
          subnet.environment ? h('span.tag', {}, subnet.environment) : null)),
      h('div.actions', {}, can('editor') ? [
        h('button.primary', { onclick: () => table.add() }, icon('plus'), 'Add address'),
        h('button', { onclick: async () => { if (await bulkDialog(subnet)) { await table.load(); refresh(); } } }, 'Bulk add'),
        h('button', { onclick: async () => { if (await subnetDialog(subnet)) refresh(); } }, icon('edit'), 'Edit'),
        h('button.danger', { onclick: removeSubnet }, icon('trash'), 'Delete'),
      ] : null));
  }

  async function removeSubnet() {
    const n = subnet.ip_count;
    const ok = await confirmDialog(`Delete ${subnet.name}?`,
      `This deletes the subnet${n ? ` and its ${n} documented address${n === 1 ? '' : 'es'}` : ''}, DHCP ranges and scan history. Export first if you might need it.`);
    if (!ok) return;
    await busy(null, async () => {
      await del(`/api/subnets/${id}`);
      toast(`${subnet.name} deleted`);
      location.hash = '#/subnets';
    });
  }

  function drawInfo() {
    const rows = [
      ['Range', `${subnet.first_ip} – ${subnet.last_ip}`, true],
      subnet.version === 4 ? ['Netmask', subnet.netmask, true] : null,
      ['Usable', subnet.usable_ips.toLocaleString(), true],
      ['Gateway', subnet.gateway, true],
      ['DNS', [subnet.dns_primary, subnet.dns_secondary].filter(Boolean).join(', '), true],
      ['Location', subnet.location],
      ['Tags', subnet.tags.length ? subnet.tags.map((t) => h('span.tag', {}, t)) : null],
      ['Last scan', subnet.last_scan_at ? ago(subnet.last_scan_at) : 'never'],
      ['Auto scan', subnet.auto_scan ? 'whole subnet' : 'documented IPs only'],
    ].filter((r) => r && r[1] && (!Array.isArray(r[1]) || r[1].length));
    mount(infoPanel,
      h('div.panel-head', {}, h('h2', {}, 'Details')),
      h('div.pad.stack', {},
        utilBar(subnet.utilization),
        h('dl.meta', {}, rows.map(([k, v, mono]) => [h('dt', {}, k), h('dd', { class: mono ? 'mono' : '' }, v)])),
        subnet.description ? h('p.muted', {}, subnet.description) : null,
        (subnet.warnings || []).map((w) => h('p.warn-text', {}, w))));
  }

  function drawDhcp() {
    const ranges = subnet.dhcp_ranges;
    mount(dhcpPanel,
      h('div.panel-head', {}, h('h2', {}, 'DHCP ranges'),
        can('editor') ? h('div.actions', {}, h('button.ghost', { onclick: async () => { if (await dhcpDialog(subnet)) refresh(); } }, icon('plus'), 'Add')) : null),
      ranges.length
        ? h('table', {}, h('tbody', {}, ranges.map((r) => h('tr', {},
          h('td.mono', {}, `${r.start} – ${r.end}`, r.description ? h('div.faint', {}, r.description) : null),
          h('td.muted.mono', {}, r.size),
          h('td.actions', {}, can('editor') ? [
            h('button.ghost.icon', { 'aria-label': 'Edit range', onclick: async () => { if (await dhcpDialog(subnet, r)) refresh(); } }, icon('edit')),
            h('button.ghost.icon.danger', { 'aria-label': 'Delete range', onclick: async (e) => {
              if (!(await confirmDialog('Delete DHCP range?', `${r.start} – ${r.end} will no longer be skipped by next free.`))) return;
              await busy(e.currentTarget, async () => { await del(`/api/dhcp-ranges/${r.id}`); refresh(); });
            } }, icon('trash'))] : null)))))
        : h('div.pad.muted', {}, 'No pools. Add your router\'s DHCP range so next free never hands out a leased address.'));
  }

  async function drawMap() {
    if (subnet.version !== 4 || subnet.prefix_length < 22) {
      mapPanel.classList.add('hidden');
      return;
    }
    mapPanel.classList.remove('hidden');
    const { cells } = await get(`/api/subnets/${id}/map`);
    const tip = h('div.map-tip', {}, 'Hover an address');
    const grid = h('div.map', { class: cells.length <= 256 ? 'small' : '', role: 'grid', 'aria-label': `Address map of ${subnet.cidr}` },
      cells.map((c) => {
        const label = `${c.address} · ${c.state}${c.hostname ? ` · ${c.hostname}` : ''}${c.pool ? ' · DHCP pool' : ''}`;
        const cell = h('button.cell', { type: 'button', class: `st-${c.state}${c.pool ? ' pool' : ''}`, 'aria-label': label, title: label });
        cell.addEventListener('mouseenter', () => { tip.textContent = label; });
        cell.addEventListener('focus', () => { tip.textContent = label; });
        cell.addEventListener('click', () => onCell(c));
        return cell;
      }));
    mount(mapPanel,
      h('div.panel-head', {}, h('h2', {}, 'Map'), h('span.muted.mono', {}, `${subnet.used_ips} used · ${subnet.free_ips} free`)),
      h('div.pad', {}, grid, tip,
        h('div.legend', {}, LEGEND.map(([cls, text]) => h('span', {},
          h('span.cell', { class: cls.split(' ').map((c, i) => (i ? c : `st-${c}`)).join(' ') }), text)))));
  }

  async function onCell(c) {
    if (c.state === 'reserved-net' || !can('editor')) return;
    if (c.id) { await table.edit(await get(`/api/ips/${c.id}`)); return; }
    if (c.state === 'gateway') { toast(`${c.address} is the gateway`); return; }
    if (c.pool) toast(`${c.address} is inside a DHCP pool`, 'warn');
    await table.add({ address: c.address, hostname: c.hostname || null, status: 'in-use' });
  }

  // ---------- scanning ----------
  function drawScanIdle(note) {
    mount(scanPanel,
      h('div.panel-head', {}, h('h2', {}, 'Scan')),
      h('div.pad.stack', {},
        h('p.muted', {}, note || 'Find hosts that answer on this subnet. Results feed the map and the Drift page.'),
        can('editor') ? h('div.row', {},
          h('button', { onclick: (e) => start('ping', e.currentTarget) }, icon('radar'), 'Ping sweep'),
          h('button', { onclick: (e) => start('full', e.currentTarget), title: 'OS and service detection, much slower' }, 'Full scan'))
          : null));
  }

  async function start(type, button) {
    await busy(button, async () => {
      const { job_id: jobId } = await post(`/api/subnets/${id}/scans`, { scan_type: type });
      watch(jobId);
    });
  }

  function watch(jobId) {
    const log = h('div.log', { 'aria-live': 'off' });
    const state = h('span.muted', {}, 'running…');
    mount(scanPanel, h('div.panel-head', {}, h('h2', {}, 'Scan'), state), log);
    const tick = async () => {
      let job;
      try { job = await get(`/api/scans/${jobId}`); } catch (err) { state.textContent = err.message; return; }
      const stick = log.scrollTop + log.clientHeight >= log.scrollHeight - 4;
      log.textContent = job.logs.join('\n');
      if (stick) log.scrollTop = log.scrollHeight;
      if (job.status === 'running') { pollTimer = setTimeout(tick, 1000); return; }
      if (job.status === 'error') { drawScanIdle(`Scan failed: ${job.error}`); return; }
      showResults(job);
      refresh();
      refreshDriftCount();
    };
    tick();
  }

  function showResults(job) {
    const fresh = job.discovered.filter((d) => !d.documented);
    const boxes = new Map();
    const list = fresh.length
      ? h('table', {}, h('tbody', {}, fresh.map((d) => {
        const box = h('input', { type: 'checkbox', checked: true, 'aria-label': `Import ${d.address}` });
        boxes.set(d.address, box);
        return h('tr', {}, h('td', {}, box), h('td.mono', {}, d.address),
          h('td', {}, d.hostname || h('span.faint', {}, '—'), h('div.faint.mono', {}, [d.mac_address, d.vendor].filter(Boolean).join(' · '))));
      })))
      : null;
    mount(scanPanel,
      h('div.panel-head', {}, h('h2', {}, 'Scan'), h('span.muted', {}, `${job.discovered.length} up · ${fresh.length} new`)),
      fresh.length ? list : h('div.pad.muted', {}, 'Every host that answered is already documented.'),
      h('div.pad.row', {},
        fresh.length && can('editor') ? h('button.primary', { onclick: (e) => busy(e.currentTarget, async () => {
          const addresses = [...boxes].filter(([, b]) => b.checked).map(([a]) => a);
          if (!addresses.length) return;
          const r = await post(`/api/subnets/${id}/discoveries/import`, { addresses });
          toast(`${r.created.length} address${r.created.length === 1 ? '' : 'es'} documented`);
          await table.load();
          refresh();
          refreshDriftCount();
          drawScanIdle();
        }) }, 'Document selected') : null,
        h('button', { onclick: () => drawScanIdle() }, 'Done')));
  }

  const addresses = h('section.panel', {},
    h('div.panel-head', {}, h('h2', {}, 'Addresses'), h('div.actions', {}, table.statusFilter)),
    table.el);

  mount(root, head, h('div.cols', {},
    h('div.stack', {}, mapPanel, addresses),
    h('div.stack', {}, infoPanel, dhcpPanel, scanPanel)));
  drawHead();
  drawInfo();
  drawDhcp();
  drawScanIdle();
  await Promise.all([drawMap(), table.load()]);

  return () => clearTimeout(pollTimer);
}

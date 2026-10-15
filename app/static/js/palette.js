// Command palette (Ctrl/⌘ K, or /): go anywhere, find addresses, run actions. Built like rconsole's.
import { get } from './api.js';
import { debounce, h, icon } from './dom.js';
import { can } from './state.js';

const IP_RE = /^(\d{1,3}(\.\d{1,3}){3}|[0-9a-f:]*:[0-9a-f:.]+)$/i;
const PAGES = [
  ['Subnets', '#/subnets', 'subnets'], ['Addresses', '#/addresses', 'addresses'], ['VLANs', '#/vlans', 'vlans'],
  ['Drift', '#/drift', 'drift'], ['Activity', '#/activity', 'activity'], ['Settings', '#/settings', 'settings'],
];

let dlg;
let input;
let list;
let items = [];
let active = 0;
let cache = { at: 0, subnets: [], vlans: [] };

function currentSubnet() {
  const m = location.hash.match(/^#\/subnets\/(\d+)/);
  return m ? Number(m[1]) : null;
}

async function catalog() {
  if (Date.now() - cache.at < 30000) return cache;
  const [s, v] = await Promise.all([get('/api/subnets').catch(() => ({ items: [] })), get('/api/vlans').catch(() => ({ items: [] }))]);
  cache = { at: Date.now(), subnets: s.items, vlans: v.items };
  return cache;
}

function actions() {
  const out = [];
  const sid = currentSubnet();
  if (can('editor')) {
    out.push({ label: 'New subnet', icon: 'add', run: () => run('new-subnet') });
    if (sid) out.push({ label: 'Add address to this subnet', icon: 'add', run: () => run('add-address') });
    out.push({ label: 'Import CSV', icon: 'addresses', run: () => run('import-csv') });
  }
  out.push({ label: 'Export addresses as CSV', icon: 'addresses', run: () => { location.href = '/api/export.csv?type=ips'; } });
  if (can('admin')) out.push({ label: 'Users and single sign-on', icon: 'settings', run: () => { location.hash = '#/settings'; } });
  return out.map((a) => ({ ...a, group: 'Actions' }));
}

// Actions that need the view's own state are handed to it via an event
function run(name) {
  window.dispatchEvent(new CustomEvent('lattice:action', { detail: name }));
}

function score(text, q) {
  const t = text.toLowerCase();
  if (t.startsWith(q)) return 3;
  if (t.includes(` ${q}`) || t.includes(`.${q}`)) return 2;
  return t.includes(q) ? 1 : 0;
}

async function build(q) {
  const { subnets, vlans } = await catalog();
  const out = [];
  if (IP_RE.test(q)) {
    out.push({ group: 'Look up', label: `Look up ${q}`, icon: 'search', run: () => { location.hash = `#/addresses?search=${encodeURIComponent(q)}`; } });
  }
  const ql = q.toLowerCase();
  const pages = PAGES.filter(([name]) => !q || score(name, ql)).map(([label, href, ic]) => ({ group: 'Go to', label, icon: ic, run: () => { location.hash = href; } }));
  const subs = subnets.map((s) => ({ s, n: q ? Math.max(score(s.name, ql), score(s.cidr, ql)) : 1 }))
    .filter((x) => x.n).sort((a, b) => b.n - a.n).slice(0, q ? 8 : 6)
    .map(({ s }) => ({ group: 'Subnets', label: s.name, hint: s.cidr, icon: 'subnets', run: () => { location.hash = `#/subnets/${s.id}`; } }));
  const vl = q ? vlans.filter((v) => score(`${v.vid} ${v.name}`, ql)).slice(0, 5)
    .map((v) => ({ group: 'VLANs', label: `VLAN ${v.vid} · ${v.name}`, icon: 'vlans', run: () => { location.hash = '#/vlans'; } })) : [];
  const acts = actions().filter((a) => !q || score(a.label, ql));
  out.push(...(q ? [...subs, ...vl, ...pages, ...acts] : [...pages, ...acts, ...subs]));
  return out;
}

function render() {
  active = Math.min(active, Math.max(0, items.length - 1));
  const rows = [];
  let group = null;
  items.forEach((item, idx) => {
    if (item.group !== group) {
      group = item.group;
      rows.push(h('li.palette-group', { role: 'presentation' }, group));
    }
    rows.push(h('li', { id: `pal-${idx}`, role: 'option', 'aria-selected': String(idx === active),
      onmousemove: () => { if (active !== idx) { active = idx; mark(); } },
      onclick: () => choose(idx) },
    icon(item.icon || 'search', 16), h('span.label', {}, item.label), item.hint ? h('span.hint.mono', {}, item.hint) : null));
  });
  list.replaceChildren(...(rows.length ? rows : [h('li.palette-empty', {}, 'Nothing matches. Try a subnet name, a CIDR or an address.')]));
  mark();
}

function mark() {
  list.querySelectorAll('[role=option]').forEach((li) => li.setAttribute('aria-selected', String(li.id === `pal-${active}`)));
  input.setAttribute('aria-activedescendant', `pal-${active}`);
  document.getElementById(`pal-${active}`)?.scrollIntoView({ block: 'nearest' });
}

function choose(idx) {
  const item = items[idx];
  if (!item) return;
  dlg.close();
  item.run();
}

let seq = 0;
async function update() {
  const q = input.value.trim();
  const id = ++seq;
  items = await build(q);
  if (id !== seq) return;
  active = 0;
  render();
  if (q.length >= 2) searchAddresses(q, id);
}

const searchAddresses = debounce(async (q, id) => {
  const data = await get(`/api/ips?search=${encodeURIComponent(q)}&per_page=8`).catch(() => null);
  if (!data || id !== seq || !data.items.length) return;
  const found = data.items.map((ip) => ({ group: 'Addresses', label: ip.hostname ? `${ip.address} · ${ip.hostname}` : ip.address,
    hint: ip.subnet_name, icon: 'addresses', run: () => { location.hash = `#/subnets/${ip.subnet_id}`; } }));
  const at = items.findIndex((i) => i.group !== 'Look up' && i.group !== 'Subnets');
  items.splice(at < 0 ? items.length : at, 0, ...found);
  render();
}, 180);

export function openPalette() {
  if (dlg.open) return;
  input.value = '';
  cache.at = 0;
  dlg.showModal();
  input.focus();
  update();
}

export function initPalette() {
  input = h('input', { type: 'text', placeholder: 'Go to a subnet, find an address, or run an action', role: 'combobox',
    'aria-expanded': 'true', 'aria-controls': 'palette-list', autocomplete: 'off', spellcheck: 'false' });
  list = h('ul.palette-list', { id: 'palette-list', role: 'listbox' });
  dlg = h('dialog.palette', { 'aria-label': 'Command palette' },
    h('div.palette-search', {}, icon('search', 18), input, h('kbd', {}, 'Esc')),
    list,
    h('div.palette-foot', {}, h('span', {}, h('kbd', {}, '↑'), h('kbd', {}, '↓'), ' move'), h('span', {}, h('kbd', {}, '↵'), ' open'),
      h('span', {}, h('kbd', {}, 'Esc'), ' close')));
  dlg.addEventListener('click', (e) => { if (e.target === dlg) dlg.close(); });
  document.body.append(dlg);

  input.addEventListener('input', update);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); active = Math.min(active + 1, items.length - 1); mark(); }
    if (e.key === 'ArrowUp') { e.preventDefault(); active = Math.max(active - 1, 0); mark(); }
    if (e.key === 'Enter') { e.preventDefault(); choose(active); }
  });

  document.addEventListener('keydown', (e) => {
    const typing = e.target.closest?.('input, textarea, select, [contenteditable]');
    if ((e.key === 'k' && (e.metaKey || e.ctrlKey)) || (e.key === '/' && !typing && !document.querySelector('dialog[open]'))) {
      e.preventDefault();
      openPalette();
    }
  });
}

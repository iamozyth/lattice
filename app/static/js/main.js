import { get, post } from './api.js';
import { $, $$, debounce, mount, h, toast } from './dom.js';
import { state, can } from './state.js';
import { initPalette, openPalette } from './palette.js';

const AREAS = { subnets: 'Subnets', addresses: 'Addresses', drift: 'Drift', vlans: 'VLANs', activity: 'Activity', connectors: 'Connectors', settings: 'Settings' };

const routes = [
  [/^#\/subnets\/(\d+)$/, () => import('./views/subnet.js'), 'subnets'],
  [/^#\/subnets$/, () => import('./views/subnets.js'), 'subnets'],
  [/^#\/addresses$/, () => import('./views/addresses.js'), 'addresses'],
  [/^#\/drift$/, () => import('./views/drift.js'), 'drift'],
  [/^#\/activity$/, () => import('./views/activity.js'), 'activity'],
  [/^#\/vlans$/, () => import('./views/vlans.js'), 'vlans'],
  [/^#\/connectors$/, () => import('./views/connectors.js'), 'connectors'],
  [/^#\/settings$/, () => import('./views/settings.js'), 'settings'],
];

const view = $('#view');
let cleanup = null;
let renderId = 0;

export function query() {
  const i = location.hash.indexOf('?');
  return new URLSearchParams(i >= 0 ? location.hash.slice(i + 1) : '');
}

async function route() {
  const [path] = location.hash.split('?');
  const match = routes.find(([re]) => re.test(path));
  if (!match) { location.replace('#/subnets'); return; }
  const [re, load, nav] = match;
  const id = ++renderId;
  if (cleanup) { cleanup(); cleanup = null; }
  $$('#nav a[data-nav]').forEach((a) => {
    if (a.dataset.nav === nav) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  });
  $('#area-name').textContent = AREAS[nav];
  $('#area-icon').setAttribute('href', `#pg-${nav}`);
  document.title = `${AREAS[nav]} · lattice`;
  mount(view, h('div.stack', {}, h('span.skeleton'), h('span.skeleton'), h('span.skeleton')));
  try {
    const mod = await load();
    if (id !== renderId) return;
    const params = path.match(re).slice(1);
    const result = await mod.render(view, params, query());
    if (id === renderId && typeof result === 'function') cleanup = result;
  } catch (err) {
    if (id !== renderId) return;
    mount(view, h('div.empty', {}, h('strong', {}, 'Could not load this page'), err.message));
  }
}

export async function refreshDriftCount() {
  try {
    const d = await get('/api/drift');
    const n = d.counts.undocumented + d.counts.offline + d.counts.conflicts;
    $('#drift-count').textContent = n ? String(n) : '';
  } catch { /* the badge is optional */ }
}

async function init() {
  const status = await get('/api/auth/status');
  if (!status.user) { location.href = '/login'; return; }
  state.user = status.user;
  state.version = status.version;
  state.via = status.via;
  $('#me').textContent = state.user.username;
  $('#me-initial').textContent = state.user.username.slice(0, 1);
  $('#me-role').textContent = state.user.role;
  $('#version').textContent = status.version;
  $('#me-sso').toggleAttribute('hidden', status.via !== 'sso'); // SVG has no .hidden property
  $$('[data-role]').forEach((el) => el.classList.toggle('hidden', !can(el.dataset.role)));

  document.addEventListener('click', async (e) => {
    const target = e.target.closest('[data-action]');
    if (!target) return;
    if (target.dataset.action === 'logout') {
      const out = await post('/api/auth/logout').catch(() => ({}));
      location.href = out?.redirect || '/login'; // after SSO: end the provider session too
    }
  });

  initPalette();
  $('#palette-open').addEventListener('click', openPalette);
  if (/Mac|iPhone|iPad/.test(navigator.platform)) $('#palette-key').textContent = '⌘K';

  // Actions from the palette that aren't tied to the open page
  window.addEventListener('lattice:action', async (e) => {
    if (e.detail === 'new-subnet') {
      const { subnetDialog } = await import('./forms.js');
      const list = await get('/api/subnets');
      const s = await subnetDialog(null, { environments: list.environments, subnets: list.items });
      if (s) location.hash = `#/subnets/${s.id}`;
    } else if (e.detail === 'import-csv') {
      const { csvImportDialog } = await import('./views/csvimport.js');
      if (await csvImportDialog('ips')) route();
    }
  });

  window.addEventListener('hashchange', route);
  if (!location.hash) location.replace('#/subnets');
  route();
  refreshDriftCount();
}

init().catch((err) => toast(err.message, 'error'));

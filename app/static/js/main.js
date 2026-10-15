import { get, post } from './api.js';
import { $, $$, debounce, mount, h, toast } from './dom.js';
import { state, can } from './state.js';

const routes = [
  [/^#\/subnets\/(\d+)$/, () => import('./views/subnet.js'), 'subnets'],
  [/^#\/subnets$/, () => import('./views/subnets.js'), 'subnets'],
  [/^#\/addresses$/, () => import('./views/addresses.js'), 'addresses'],
  [/^#\/drift$/, () => import('./views/drift.js'), 'drift'],
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
  if (nav !== 'addresses') $('#search').value = '';
  mount(view, h('p.muted', {}, 'loading…'));
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
  $('#who').textContent = state.user.username;
  $$('[data-role]').forEach((el) => el.classList.toggle('hidden', !can(el.dataset.role)));

  document.addEventListener('click', async (e) => {
    const target = e.target.closest('[data-action]');
    if (!target) return;
    if (target.dataset.action === 'logout') {
      await post('/api/auth/logout').catch(() => {});
      location.href = '/login';
    }
  });

  const search = $('#search');
  const goSearch = debounce(() => {
    const q = search.value.trim();
    const target = q ? `#/addresses?search=${encodeURIComponent(q)}` : '#/addresses';
    if (location.hash !== target) location.hash = target;
  }, 300);
  search.addEventListener('input', goSearch);
  $('#search-form').addEventListener('submit', (e) => { e.preventDefault(); goSearch(); });

  document.addEventListener('keydown', (e) => {
    const typing = e.target.closest('input, textarea, select, [contenteditable]');
    if (e.key === '/' && !typing && !document.querySelector('dialog[open]')) {
      e.preventDefault();
      search.focus();
      search.select();
    }
  });

  window.addEventListener('hashchange', route);
  if (!location.hash) location.replace('#/subnets');
  route();
  refreshDriftCount();
}

init().catch((err) => toast(err.message, 'error'));

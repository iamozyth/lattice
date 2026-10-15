import { del, get, post, put } from '../api.js';
import { busy, confirmDialog, dialog, field, h, icon, input, mount, select, toast } from '../dom.js';
import { can, state } from '../state.js';
import { csvImportDialog } from './csvimport.js';

export async function render(root) {
  const sections = [account()];
  if (can('admin')) sections.push(await users(), await sso());
  if (can('editor')) sections.push(await tags());
  sections.push(data(), about());
  mount(root, h('div.stack', {}, sections));
}

function account() {
  const who = `${state.user.username} · ${state.user.email} · ${state.user.role}`;
  if (state.user.source === 'sso') {
    return h('section.panel', {},
      h('div.panel-head', {}, h('h3', {}, 'Account'), h('span.pill.own', {}, 'Single sign-on')),
      h('div.pad', {}, h('p.muted', {}, who), h('p.note', {}, 'Your password, passkeys and two-factor sign-in are managed by your identity provider.')));
  }
  const form = h('form.pad.stack', { onsubmit: async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    if (fd.get('new_password') !== fd.get('confirm')) { toast('The new passwords do not match', 'error'); return; }
    await busy(form.querySelector('button'), async () => {
      await post('/api/auth/password', { current_password: fd.get('current_password'), new_password: fd.get('new_password') });
      form.reset();
      toast('Password changed. Other sessions were signed out.');
    });
  } },
  h('div.grid-2', {},
    h('div.wide', {}, field('Current password', input('current_password', '', { type: 'password', autocomplete: 'current-password', required: true }))),
    field('New password', input('new_password', '', { type: 'password', autocomplete: 'new-password', minlength: 8, required: true })),
    field('Repeat new password', input('confirm', '', { type: 'password', autocomplete: 'new-password', minlength: 8, required: true }))),
  h('div', {}, h('button', { type: 'submit' }, 'Change password')));
  return h('section.panel', {},
    h('div.panel-head', {}, h('h3', {}, 'Account')),
    h('div.pad', { class: 'flush' }, h('span.muted', {}, `${state.user.username} · ${state.user.email} · ${state.user.role}`)),
    form);
}

const ROLE_HELP = { viewer: 'can look, not change', editor: 'can change subnets and addresses', admin: 'also users, connectors and imports' };

async function users() {
  const panel = h('section.panel');
  async function load() {
    const { items } = await get('/api/auth/users');
    mount(panel,
      h('div.panel-head', {}, h('h3', {}, 'Users'),
        h('div.actions', {}, h('button.ghost', { onclick: () => edit() }, 'Add user'))),
      h('div.table-wrap', {}, h('table', {}, h('tbody', {}, items.map((u) => h('tr', {},
        h('td', {}, h('strong', {}, u.username), u.id === state.user.id ? h('span.faint', {}, ' (you)') : null,
          u.source === 'sso' ? [' ', h('span.pill.own', {}, 'SSO')] : null, h('span.sub', {}, u.email)),
        h('td', { title: ROLE_HELP[u.role] }, u.role),
        h('td', {}, u.is_active ? h('span.status.s-in-use', {}, 'active') : h('span.status.s-deprecated', {}, 'disabled')),
        h('td.actions', {}, u.id === state.user.id ? null : [
          h('button.ghost.icon.hover', { 'aria-label': `Edit ${u.username}`, onclick: () => edit(u) }, icon('edit')),
          h('button.ghost.icon.danger.hover', { 'aria-label': `Delete ${u.username}`, onclick: async () => {
            if (!(await confirmDialog(`Delete ${u.username}?`, 'They are signed out and can no longer log in.'))) return;
            await busy(null, async () => { await del(`/api/auth/users/${u.id}`); load(); });
          } }, icon('delete'))])))))));
  }
  async function edit(u = null) {
    const saved = await dialog({
      title: u ? `Edit ${u.username}` : 'Add user',
      body: h('div.grid-2', {},
        u ? null : field('Username', input('username', '', { required: true, minlength: 3 })),
        field('Email', input('email', u?.email, { type: 'email', required: true })),
        field('Role', select('role', [['viewer', 'Viewer'], ['editor', 'Editor'], ['admin', 'Admin']], u?.role || 'viewer')),
        u?.source === 'sso' ? null : field(u ? 'New password' : 'Password', input('password', '', { type: 'password', autocomplete: 'new-password', minlength: 8, required: !u }),
          u ? 'Leave blank to keep the current password' : 'At least 8 characters'),
        u ? h('label.check.wide', {}, h('input', { type: 'checkbox', name: 'is_active', checked: u.is_active }), 'Account enabled') : null),
      onSubmit: (fd) => {
        const body = { email: fd.get('email'), role: fd.get('role') };
        if (fd.get('password')) body.password = fd.get('password');
        if (u) return put(`/api/auth/users/${u.id}`, { ...body, is_active: fd.get('is_active') === 'on' });
        return post('/api/auth/users', { ...body, username: fd.get('username') });
      },
    });
    if (saved) load();
  }
  await load();
  return panel;
}

function data() {
  const file = h('input', { type: 'file', accept: 'application/json,.json', class: 'hidden' });
  const mode = select('mode', [['merge', 'Merge: add what is missing'], ['replace', 'Replace: delete everything first']], 'merge');
  file.addEventListener('change', async () => {
    const f = file.files[0];
    file.value = '';
    if (!f) return;
    let payload;
    try { payload = JSON.parse(await f.text()); } catch { toast('That file is not valid JSON', 'error'); return; }
    if (mode.value === 'replace' && !(await confirmDialog('Replace all data?',
      'Every subnet, address, DHCP range and discovery is deleted and replaced with the file. Nothing changes if the file has an error.', 'Replace'))) return;
    await busy(null, async () => {
      const r = await post(`/api/import?mode=${mode.value}`, payload);
      toast(`Imported ${r.subnets} subnets, ${r.ips} addresses, ${r.dhcp_ranges} DHCP ranges`);
    });
  });
  return h('section.panel', {},
    h('div.panel-head', {}, h('h3', {}, 'Data')),
    h('div.pad.stack', {},
      h('div.row', {}, h('a.btn', { href: '/api/export', download: '' }, 'Export JSON'),
        h('span.muted', {}, 'Everything: subnets, addresses, DHCP ranges, VLANs and tags. Use it as a backup.')),
      h('div.row', {}, h('a.btn', { href: '/api/export.csv?type=ips', download: '' }, 'Addresses CSV'),
        h('a.btn', { href: '/api/export.csv?type=subnets', download: '' }, 'Subnets CSV'),
        can('editor') ? h('button', { onclick: () => csvImportDialog('ips') }, 'Import CSV…') : null,
        h('span.muted', {}, 'For spreadsheets and other tools.')),
      can('admin') ? h('div.row', {}, mode, h('button', { onclick: () => file.click() }, 'Import JSON…'), file) : null));
}

function about() {
  const result = h('span.muted');
  return h('section.panel', {},
    h('div.panel-head', {}, h('h3', {}, 'About')),
    h('div.pad.row', {},
      h('span.mono', {}, `lattice ${state.version}`),
      h('a', { href: 'https://github.com/iamozyth/lattice', target: '_blank', rel: 'noopener' }, 'GitHub'),
      h('a', { href: '/openapi/swagger', target: '_blank', rel: 'noopener' }, 'API docs'),
      can('admin') ? h('button', { onclick: (e) => busy(e.currentTarget, async () => {
        const r = await get('/api/auth/updates');
        if (r.error) result.textContent = r.error;
        else if (r.update_available) mount(result, `${r.latest_version} is available · `, h('a', { href: r.release_url, target: '_blank', rel: 'noopener' }, 'release notes'));
        else if (r.ahead) result.textContent = `This build is newer than the latest release (${r.latest_version}).`;
        else result.textContent = 'Up to date.';
      }) }, 'Check for updates') : null,
      result));
}

// ---------------------------------------------------------------------------
// Single sign-on (OpenID Connect): authentik, Keycloak, Pocket ID, ...
// ---------------------------------------------------------------------------

async function sso() {
  const panel = h('section.panel');
  let cfg = await get('/api/settings/sso');

  function lockable(name, el) {
    if (cfg.locked[name]) { el.disabled = true; el.title = 'Set on the server (OIDC_* environment variable)'; }
    return el;
  }
  const lockNote = (name) => (cfg.locked[name] ? h('span.lock', {}, 'set on the server') : null);

  function draw() {
    const enabled = h('input', { type: 'checkbox', name: 'enabled', checked: cfg.enabled });
    lockable('issuer', enabled);
    const copy = h('button', { type: 'button', 'aria-label': 'Copy redirect URI', title: 'Copy', class: 'icon',
      onclick: () => navigator.clipboard?.writeText(cfg.redirect_uri).then(() => toast('Redirect URI copied')) }, icon('copy'));
    const form = h('form.pad.stack', { onsubmit: (e) => { e.preventDefault(); saveForm(form, e.submitter); } },
      h('label.switch', {}, enabled, 'Use single sign-on'),
      h('ol.sso-steps', {},
        h('li', {}, 'In authentik: ', h('b', {}, 'Applications → Providers → Create → OAuth2/OpenID Provider'),
          ', confidential client, ', h('b', {}, 'Signing Key'), ' set (any certificate).'),
        h('li', {}, 'Redirect URI (strict):', h('div.copy-row', {}, h('input.mono', { value: cfg.redirect_uri, readonly: true, 'aria-label': 'Redirect URI' }), copy)),
        h('li', {}, 'Create an application ', h('b', {}, 'lattice'), ' with that provider, and the groups below. People in none of them are refused.')),
      h('div.grid-2', {},
        h('div.wide', {}, field(h('span', {}, 'Issuer URL ', lockNote('issuer')), lockable('issuer', input('issuer', cfg.issuer, { class: 'mono', placeholder: 'https://auth.example.com/application/o/lattice/' })))),
        field(h('span', {}, 'Client ID ', lockNote('client_id')), lockable('client_id', input('client_id', cfg.client_id, { class: 'mono' }))),
        field(h('span', {}, 'Client secret ', lockNote('client_secret')), lockable('client_secret', input('client_secret', '', { type: 'password', autocomplete: 'off', placeholder: cfg.has_secret ? 'Saved; leave blank to keep' : '' }))),
        field(h('span', {}, 'Button label ', lockNote('name')), lockable('name', input('name', cfg.name, { placeholder: 'authentik' })), `Shown as “Continue with ${cfg.name}”`),
        field(h('span', {}, 'Session length (hours) ', lockNote('session_hours')), lockable('session_hours', input('session_hours', cfg.session_hours, { type: 'number', min: 1, max: 168 })), 'Removing someone at the provider takes effect within this time'),
        field(h('span', {}, 'Admin groups ', lockNote('groups.admin')), lockable('groups.admin', input('admin', cfg.groups.admin.join(', '), { class: 'mono' }))),
        field(h('span', {}, 'Editor groups ', lockNote('groups.editor')), lockable('groups.editor', input('editor', cfg.groups.editor.join(', '), { class: 'mono' }))),
        field(h('span', {}, 'Viewer groups ', lockNote('groups.viewer')), lockable('groups.viewer', input('viewer', cfg.groups.viewer.join(', '), { class: 'mono' })), 'Comma-separated group names from the provider')),
      h('label.switch', {}, lockable('local_login', h('input', { type: 'checkbox', name: 'local_login', checked: cfg.local_login })),
        'Allow local accounts as a fallback'),
      cfg.enabled && !cfg.you_use_sso ? h('p.note', {}, 'Sign in once with single sign-on (try a private window) before turning local accounts off.') : null,
      h('p.error-box', { role: 'alert' }),
      h('div.form-actions', {},
        h('span.grow', {}, cfg.active ? h('span.pill.ok', {}, `On · Continue with ${cfg.name}`) : h('span.pill', {}, 'Off')),
        h('button.primary', { type: 'submit' }, cfg.enabled ? 'Save and test' : 'Save')));
    enabled.addEventListener('change', () => { form.querySelector('button.primary').textContent = enabled.checked ? 'Save and test' : 'Save'; });
    mount(panel, h('div.panel-head', {}, h('h3', {}, 'Single sign-on'), h('span.meta', {}, 'OpenID Connect: authentik, Keycloak, Pocket ID')), form);
  }

  async function saveForm(form, button) {
    const fd = new FormData(form);
    const err = form.querySelector('.error-box');
    err.textContent = '';
    // Locked (env) fields are disabled, so FormData leaves them out: send only the rest
    const body = { groups: {} };
    if (!cfg.locked.issuer) body.enabled = fd.get('enabled') === 'on';
    if (!cfg.locked.local_login) body.local_login = fd.get('local_login') === 'on';
    for (const r of ['admin', 'editor', 'viewer']) if (fd.has(r)) body.groups[r] = fd.get(r);
    for (const k of ['issuer', 'client_id', 'client_secret', 'name', 'session_hours']) if (fd.has(k)) body[k] = fd.get(k);
    if (button) button.disabled = true;
    try {
      cfg = await put('/api/settings/sso', body);
      toast(cfg.active ? `Single sign-on is on. Try it in a private window before you sign out.` : 'Single sign-on is off');
      draw();
    } catch (e) {
      err.textContent = e.message;
    } finally {
      if (button) button.disabled = false;
    }
  }

  draw();
  return panel;
}

// ---------------------------------------------------------------------------
// Tags: rename (renaming onto an existing tag merges them) and delete
// ---------------------------------------------------------------------------

async function tags() {
  const panel = h('section.panel');
  async function load() {
    const { items } = await get('/api/tags');
    mount(panel,
      h('div.panel-head', {}, h('h3', {}, 'Tags'), h('span.meta', {}, `${items.length} tag${items.length === 1 ? '' : 's'}`)),
      items.length ? h('div.table-wrap', {}, h('table', {}, h('tbody', {}, items.map((t) => h('tr', {},
        h('td', {}, h('span.pill', {}, t.name)),
        h('td.muted', {}, [
          t.subnets ? h('a', { href: `#/subnets?tag=${encodeURIComponent(t.name)}` }, `${t.subnets} subnet${t.subnets === 1 ? '' : 's'}`) : null,
          t.subnets && t.ips ? ' · ' : null,
          t.ips ? h('a', { href: `#/addresses?tag=${encodeURIComponent(t.name)}` }, `${t.ips} address${t.ips === 1 ? '' : 'es'}`) : null,
          !t.subnets && !t.ips ? 'unused' : null]),
        h('td.actions', {},
          h('button.ghost.icon.hover', { 'aria-label': `Rename ${t.name}`, onclick: () => rename(t) }, icon('edit')),
          h('button.ghost.icon.danger.hover', { 'aria-label': `Delete ${t.name}`, onclick: async () => {
            if (!(await confirmDialog(`Delete tag ${t.name}?`, 'It is removed from every subnet and address.'))) return;
            await busy(null, async () => { await del(`/api/tags/${t.id}`); load(); });
          } }, icon('delete'))))))))
        : h('div.pad.note', {}, 'Tags appear here once you add them to subnets or addresses.'));
  }
  async function rename(t) {
    const saved = await dialog({
      title: `Rename ${t.name}`,
      body: field('New name', input('name', t.name, { required: true, maxlength: 50 }), 'Use the name of another tag to merge the two.'),
      onSubmit: (fd) => put(`/api/tags/${t.id}`, { name: fd.get('name') }),
    });
    if (saved) load();
  }
  await load();
  return panel;
}

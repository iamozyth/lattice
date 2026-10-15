import { del, get, post, put } from '../api.js';
import { busy, confirmDialog, dialog, field, h, icon, input, mount, pageHead, select, toast } from '../dom.js';
import { can, state } from '../state.js';

export async function render(root) {
  const sections = [account()];
  if (can('admin')) sections.push(await users());
  sections.push(data(), about());
  mount(root, pageHead('Settings'), h('div.stack', {}, sections));
}

function account() {
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
        h('td', {}, h('strong', {}, u.username), u.id === state.user.id ? h('span.faint', {}, ' (you)') : null, h('div.faint', {}, u.email)),
        h('td', { title: ROLE_HELP[u.role] }, u.role),
        h('td', {}, u.is_active ? h('span.status.s-in-use', {}, 'active') : h('span.status.s-deprecated', {}, 'disabled')),
        h('td.actions', {}, u.id === state.user.id ? null : [
          h('button.ghost.icon.hover', { 'aria-label': `Edit ${u.username}`, onclick: () => edit(u) }, icon('edit')),
          h('button.ghost.icon.danger.hover', { 'aria-label': `Delete ${u.username}`, onclick: async () => {
            if (!(await confirmDialog(`Delete ${u.username}?`, 'They are signed out and can no longer log in.'))) return;
            await busy(null, async () => { await del(`/api/auth/users/${u.id}`); load(); });
          } }, icon('trash'))])))))));
  }
  async function edit(u = null) {
    const saved = await dialog({
      title: u ? `Edit ${u.username}` : 'Add user',
      body: h('div.grid-2', {},
        u ? null : field('Username', input('username', '', { required: true, minlength: 3 })),
        field('Email', input('email', u?.email, { type: 'email', required: true })),
        field('Role', select('role', [['viewer', 'Viewer'], ['editor', 'Editor'], ['admin', 'Admin']], u?.role || 'viewer')),
        field(u ? 'New password' : 'Password', input('password', '', { type: 'password', autocomplete: 'new-password', minlength: 8, required: !u }),
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
        h('span.muted', {}, 'Subnets, addresses and DHCP ranges. Use it as a backup.')),
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

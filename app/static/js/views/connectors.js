import { del, get, post, put } from '../api.js';
import { ago, busy, confirmDialog, dialog, empty, field, h, icon, input, mount, pageHead, select, toast } from '../dom.js';
import { refreshDriftCount } from '../main.js';

export async function render(root) {
  const list = h('div.stack');

  async function load() {
    const data = await get('/api/connectors');
    if (!data.items.length) {
      mount(list, h('div.panel', {}, empty('No connectors',
        'Add a UniFi console to pull in every client it knows about.')));
      return;
    }
    mount(list, data.items.map(card));
  }

  function card(c) {
    const d = c.details;
    return h('section.panel', {},
      h('div.panel-head', {}, h('span.dot', { class: c.enabled ? '' : 'off' }), h('strong', {}, c.name),
        h('span.tag', {}, c.enabled ? c.type : `${c.type} · disabled`), h('div.actions', {},
          h('button', { onclick: (e) => test(c, e.currentTarget) }, 'Test'),
          h('button.primary', { onclick: (e) => preview(c, e.currentTarget) }, 'Sync…'),
          h('button.ghost.icon.hover', { 'aria-label': `Edit ${c.name}`, onclick: () => edit(c) }, icon('edit')),
          h('button.ghost.icon.danger.hover', { 'aria-label': `Delete ${c.name}`, onclick: () => remove(c) }, icon('trash')))),
      h('div.pad', {}, h('dl.meta-list', {},
        h('dt', {}, 'URL'), h('dd.mono', {}, d.base_url || '—'),
        h('dt', {}, 'Site'), h('dd.mono', {}, d.site_id || '—'),
        h('dt', {}, 'Auth'), h('dd', {}, d.auth === 'api_key' ? 'API key' : `Username ${d.username || ''}`,
          d.verify_ssl ? '' : h('span.warn-text', {}, ' · TLS not verified')),
        h('dt', {}, 'Last sync'), h('dd', {}, ago(c.last_sync_at))),
      c.credentials_ok ? null : h('p.warn-text', {}, 'Stored credentials cannot be decrypted. Edit the connector and enter them again.')));
  }

  async function test(c, button) {
    await busy(button, async () => {
      try {
        const r = await post(`/api/connectors/${c.id}/test`);
        toast(`${c.name}: connected, ${r.hosts} clients`);
      } catch (err) {
        toast(`${c.name}: ${err.message}`, 'error');
      }
    });
  }

  async function preview(c, button) {
    const plan = await busy(button, () => post(`/api/connectors/${c.id}/sync?dry_run=true`));
    if (!plan) return;
    const section = (title, items, row) => (items.length ? h('div.stack', {}, h('h3', {}, `${title} · ${items.length}`),
      h('div.table-wrap', {}, h('table', {}, h('tbody', {}, items.slice(0, 300).map(row))))) : null);
    const body = h('div.stack', {},
      h('p.muted', {}, `${plan.hosts} clients reported. New hosts are added as in-use; existing addresses only get empty fields filled.`),
      section('Add', plan.add, (a) => h('tr', {}, h('td.mono', {}, a.ip), h('td', {}, a.hostname || '—'), h('td.muted', {}, a.subnet))),
      section('Update', plan.update, (u) => h('tr', {}, h('td.mono', {}, u.ip), h('td.muted', {},
        Object.entries(u.changes).map(([k, v]) => `${k}: ${v}`).join(', ')))),
      section('Skip', plan.skip, (s) => h('tr', {}, h('td.mono', {}, s.ip || '—'), h('td', {}, s.hostname || ''), h('td.muted', {}, s.reason))));
    const changes = plan.add.length + plan.update.length;
    const applied = await dialog({
      title: `Sync ${c.name}`, wide: true, body,
      submitLabel: changes ? `Apply ${changes} change${changes === 1 ? '' : 's'}` : 'Record sightings',
      onSubmit: () => post(`/api/connectors/${c.id}/sync`),
    });
    if (applied) {
      toast(`${c.name}: ${applied.add.length} added, ${applied.update.length} updated`);
      refreshDriftCount();
      load();
    }
  }

  async function remove(c) {
    if (!(await confirmDialog(`Delete ${c.name}?`, 'Stored credentials are removed. Addresses it added stay.'))) return;
    await del(`/api/connectors/${c.id}`);
    load();
  }

  async function edit(c = null) {
    const d = c?.details || {};
    const auth = select('auth', [['api_key', 'API key'], ['password', 'Username and password']], d.auth || 'api_key');
    const keyRow = field('API key', input('api_key', '', { type: 'password', placeholder: c ? 'Leave blank to keep' : '', autocomplete: 'new-password' }),
      'UniFi OS: Settings → Control Plane → Integrations');
    const userRow = h('div.grid-2', {},
      field('Username', input('username', d.username, { autocomplete: 'off' })),
      field('Password', input('password', '', { type: 'password', placeholder: c ? 'Leave blank to keep' : '', autocomplete: 'new-password' })));
    const sync = () => {
      keyRow.classList.toggle('hidden', auth.value !== 'api_key');
      userRow.classList.toggle('hidden', auth.value === 'api_key');
    };
    auth.addEventListener('change', sync);
    sync();
    const saved = await dialog({
      title: c ? `Edit ${c.name}` : 'Add UniFi connector',
      body: h('div.stack', {},
        field('Name', input('name', c?.name || 'UniFi', { required: true })),
        field('Console URL', input('base_url', d.base_url, { required: true, placeholder: 'https://192.168.1.1', class: 'mono' })),
        field('Site ID', input('site_id', d.site_id || 'default', { class: 'mono' })),
        field('Authentication', auth), keyRow, userRow,
        h('label.check', {}, h('input', { type: 'checkbox', name: 'verify_ssl', checked: d.verify_ssl ?? false }),
          'Verify TLS certificate (leave off for the console\'s self-signed certificate)'),
        h('label.check', {}, h('input', { type: 'checkbox', name: 'enabled', checked: c ? c.enabled : true }), 'Enabled')),
      onSubmit: (fd) => {
        const config = {
          base_url: fd.get('base_url'), site_id: fd.get('site_id'), auth: fd.get('auth'),
          api_key: fd.get('api_key'), username: fd.get('username'), password: fd.get('password'),
          verify_ssl: fd.get('verify_ssl') === 'on',
        };
        const payload = { name: fd.get('name'), enabled: fd.get('enabled') === 'on', config };
        return c ? put(`/api/connectors/${c.id}`, payload) : post('/api/connectors', { ...payload, type: 'unifi' });
      },
    });
    if (saved) { toast('Connector saved'); load(); }
  }

  mount(root,
    pageHead('Connectors', 'pull hosts in from other systems', h('button.primary', { onclick: () => edit() }, 'Add connector')),
    list);
  await load();
}

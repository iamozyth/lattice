import { del, get } from '../api.js';
import { busy, confirmDialog, empty, h, icon, mount, pageHead, toast, utilBar } from '../dom.js';
import { vlanDialog } from '../forms.js';
import { can } from '../state.js';

export async function render(root) {
  const panel = h('section.panel');

  async function load() {
    const { items } = await get('/api/vlans');
    if (!items.length) {
      mount(panel, empty('No VLANs yet', 'Add the VLANs you run, then pick them on subnets.'));
      return;
    }
    mount(panel, h('div.table-wrap', {}, h('table', {},
      h('thead', {}, h('tr', {}, h('th', {}, 'ID'), h('th', {}, 'Name'), h('th.opt', {}, 'Site'), h('th', {}, 'Subnets'), h('th', {}, h('span.sr-only', {}, 'Actions')))),
      h('tbody', {}, items.map((v) => h('tr', {},
        h('td.mono', {}, v.vid),
        h('td', {}, h('strong', {}, v.name), v.description ? h('span.sub', { title: v.description }, v.description) : null),
        h('td.muted.opt', {}, v.site || ''),
        h('td', {}, v.subnets.length
          ? v.subnets.map((s) => h('div.row', {}, h('a', { href: `#/subnets/${s.id}` }, s.name), h('span.mono.faint', {}, s.cidr), utilBar(s.utilization)))
          : h('span.faint', {}, 'No subnets')),
        h('td.actions', {}, can('editor') ? [
          h('button.ghost.icon.hover', { 'aria-label': `Edit VLAN ${v.vid}`, onclick: async () => { if (await vlanDialog(v)) load(); } }, icon('edit')),
          h('button.ghost.icon.danger.hover', { 'aria-label': `Delete VLAN ${v.vid}`, onclick: async (e) => {
            const n = v.subnets.length;
            if (!(await confirmDialog(`Delete VLAN ${v.vid}?`, n ? `${n} subnet${n === 1 ? '' : 's'} will no longer be linked to a VLAN.` : 'Nothing uses it.'))) return;
            await busy(e.currentTarget, async () => { await del(`/api/vlans/${v.id}`); toast(`VLAN ${v.vid} deleted`); load(); });
          } }, icon('delete'))] : null)))))));
  }

  mount(root,
    pageHead(null, 'The VLANs on your network and the subnets that use them.',
      can('editor') ? h('button.primary', { onclick: async () => { if (await vlanDialog()) load(); } }, 'New VLAN') : null),
    panel);
  await load();
}

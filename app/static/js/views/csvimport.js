// Import addresses or subnets from CSV: preview row by row, then apply.
import { post } from '../api.js';
import { dialog, field, h, mount, select, toast } from '../dom.js';

const ACTION = { create: 'Add', update: 'Update', unchanged: 'Same', error: 'Error' };

export async function csvImportDialog(type = 'ips') {
  let text = '';
  let preview = null;
  const kind = select('type', [['ips', 'Addresses'], ['subnets', 'Subnets']], type);
  const file = h('input', { type: 'file', accept: '.csv,text/csv,text/plain' });
  const pick = h('button', { type: 'button', onclick: () => file.click() }, 'Choose file…');
  const name = h('span.muted', {}, 'No file chosen');
  const result = h('div.stack');
  const hint = h('p.note', {}, 'Columns are matched by name; exports from lattice, phpIPAM and NetBox work as they are. Empty cells leave existing values unchanged. Addresses go into the subnet that contains them.');

  async function check() {
    if (!text) return;
    mount(result, h('p.note', {}, 'Checking…'));
    try {
      preview = await post(`/api/import/csv?type=${kind.value}&dry_run=1`, { csv: text });
    } catch (err) {
      preview = null;
      mount(result, h('p.error-box', {}, err.message));
      return;
    }
    const c = preview.counts;
    const rows = preview.rows.filter((r) => r.action !== 'unchanged').slice(0, 200);
    mount(result,
      h('div.row', {}, h('span.pill.ok', {}, `${c.create} new`), h('span.pill', {}, `${c.update} changed`),
        h('span.pill', {}, `${c.unchanged} unchanged`), c.error ? h('span.pill.bad', {}, `${c.error} with errors`) : null),
      rows.length ? h('div.table-wrap.preview', {}, h('table', {}, h('tbody', {}, rows.map((r) => h('tr', {},
        h('td.faint.mono', {}, r.line),
        h('td', {}, h('span.pill', { class: r.action === 'error' ? 'bad' : r.action === 'create' ? 'ok' : '' }, ACTION[r.action])),
        h('td.mono', {}, r.address || r.cidr || ''),
        h('td.muted', {}, r.error || (r.changes ? Object.keys(r.changes).join(', ') : r.subnet || ''))))))) : null,
      c.error ? h('p.note', {}, 'Fix the rows with errors and choose the file again; nothing is imported while errors remain.') : null);
  }

  file.addEventListener('change', async () => {
    const f = file.files[0];
    if (!f) return;
    if (f.size > 5 * 1024 * 1024) { toast('That file is larger than 5 MB', 'error'); return; }
    name.textContent = f.name;
    text = await f.text();
    check();
  });
  kind.addEventListener('change', check);

  return dialog({
    title: 'Import CSV',
    wide: true,
    body: h('div.stack', {}, h('div.grid-2', {}, field('Import', kind), field('File', h('div.row', {}, pick, name, file))), hint, result),
    submitLabel: 'Import',
    onSubmit: async () => {
      if (!preview) throw new Error('Choose a CSV file first');
      if (preview.counts.error) throw new Error('Some rows have errors; fix them first');
      if (!preview.counts.create && !preview.counts.update) throw new Error('Nothing to import: every row is already up to date');
      const r = await post(`/api/import/csv?type=${kind.value}`, { csv: text });
      toast(`Imported: ${r.counts.create} new, ${r.counts.update} updated`);
      return r;
    },
  });
}

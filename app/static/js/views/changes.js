// Renders change history entries; shared by the Activity page, the subnet page and the address dialog.
import { ago, h } from '../dom.js';

const VERB = { create: 'added', update: 'changed', delete: 'deleted' };
const NOUN = { subnet: 'subnet', ip: 'address', dhcp_range: 'DHCP range', user: 'user', connector: 'connector',
  setting: 'setting', vlan: 'VLAN', tag: 'tag' };
const FIELD = { mac_address: 'MAC', fqdn: 'FQDN', dns_primary: 'DNS', dns_secondary: 'DNS 2', subnet_id: 'subnet',
  password_hash: 'password', config_encrypted: 'credentials', is_active: 'active', vlan_id: 'VLAN',
  start_address: 'start', end_address: 'end', device_type: 'device', serial_number: 'serial' };

const show = (v) => (v === null || v === undefined || v === '' ? '—' : Array.isArray(v) ? (v.join(', ') || '—') : String(v));

function diffLines(c) {
  if (c.action !== 'update') return null;
  return Object.entries(c.diff).slice(0, 6).map(([k, v]) => h('div.change-diff', {},
    h('span.faint', {}, FIELD[k] || k.replaceAll('_', ' ')), ' ',
    Array.isArray(v) ? [h('span.old', {}, show(v[0])), ' → ', h('span', {}, show(v[1]))] : h('span', {}, v)));
}

function target(c) {
  const label = c.label || `#${c.entity_id}`;
  if (c.entity === 'subnet' && c.action !== 'delete') return h('a', { href: `#/subnets/${c.entity_id}` }, label);
  if ((c.entity === 'ip' || c.entity === 'dhcp_range') && c.subnet_id) return h('a', { href: `#/subnets/${c.subnet_id}` }, label);
  return h('strong', {}, label);
}

export function changeRows(items, { compact = false } = {}) {
  return items.map((c) => h('li.change', {},
    h('div.change-head', {},
      h('span', {}, h('strong', {}, c.username), ` ${VERB[c.action] || c.action} `,
        compact && c.entity === 'ip' ? null : `${NOUN[c.entity] || c.entity} `, compact && c.entity === 'ip' ? 'this address' : target(c)),
      h('time.faint', { datetime: c.at, title: new Date(`${c.at}Z`).toLocaleString() }, ago(c.at))),
    diffLines(c)));
}

export function changeList(items, opts) {
  return h('ul.changes', {}, changeRows(items, opts));
}

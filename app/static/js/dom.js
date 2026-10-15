// DOM helpers. h() only ever sets text via textContent, so server data is never parsed as HTML.
export function h(tag, attrs = {}, ...children) {
  const [name, ...classes] = tag.split('.');
  const el = document.createElement(name || 'div');
  if (classes.length) el.classList.add(...classes);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === 'class') el.classList.add(...String(value).split(' ').filter(Boolean));
    else if (key === 'dataset') Object.assign(el.dataset, value);
    else if (key.startsWith('on')) el.addEventListener(key.slice(2), value);
    else if (key === 'value') el.value = value;
    else if (key === 'checked' || key === 'disabled' || key === 'selected') el[key] = Boolean(value);
    else el.setAttribute(key, value === true ? '' : value);
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

export function icon(name, size = 15) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('width', size);
  svg.setAttribute('height', size);
  svg.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  use.setAttribute('href', `#pg-${name}`);
  svg.append(use);
  return svg;
}

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function mount(target, ...children) {
  target.replaceChildren();
  append(target, children);
}

export function debounce(fn, ms = 250) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

export function toast(message, kind = 'ok', ms = 4000) {
  const el = h('div.toast', { class: kind === 'ok' ? '' : kind },
    icon(kind === 'ok' ? 'check' : 'alert', 16), h('span', {}, message));
  document.getElementById('toasts').append(el);
  setTimeout(() => el.remove(), kind === 'error' ? ms * 2 : ms);
}

// Disable a button while an async action runs; errors become toasts.
export async function busy(button, fn) {
  if (button) button.disabled = true;
  try {
    return await fn();
  } catch (err) {
    toast(err.message || 'Something went wrong', 'error');
    return undefined;
  } finally {
    if (button) button.disabled = false;
  }
}

export function status(value) {
  return h('span.status', { class: `s-${value}` }, value || '—');
}

export function ago(iso) {
  if (!iso) return 'never';
  const seconds = (Date.now() - new Date(iso + (iso.endsWith('Z') ? '' : 'Z'))) / 1000;
  if (seconds < 60) return 'just now';
  const units = [['minute', 60], ['hour', 3600], ['day', 86400], ['month', 2592000], ['year', 31536000]];
  let label = 'minute', size = 60;
  for (const [name, s] of units) if (seconds >= s) { label = name; size = s; }
  const n = Math.floor(seconds / size);
  return `${n} ${label}${n === 1 ? '' : 's'} ago`;
}

export function utilBar(percent) {
  const fill = h('i');
  fill.style.width = `${Math.min(100, percent)}%`;
  const level = percent >= 90 ? 'high' : percent >= 70 ? 'mid' : '';
  return h('span.util', {}, h('span.bar', { class: level }, fill), `${percent}%`);
}

export function empty(title, text) {
  return h('div.empty', {}, h('strong', {}, title), text ? h('div', {}, text) : null);
}

// Page heading: title, a muted summary and actions on the right
export function pageHead(title, meta, ...actions) {
  return h('div.head', {}, title ? h('h2', {}, title) : null, meta ? h('span.meta', {}, meta) : null,
    actions.some(Boolean) ? h('div.actions', {}, ...actions) : null);
}

export function panelHead(title, ...right) {
  return h('div.panel-head', {}, h('h3', {}, title), right.some(Boolean) ? h('div.actions', {}, ...right) : null);
}

// ---------- dialogs ----------

// Opens a <dialog>; resolves with the value passed to close(), or undefined when dismissed.
export function dialog({ title, wide = false, body, actions = [], onSubmit, submitLabel = 'Save', danger = false }) {
  return new Promise((resolve) => {
    const error = h('p.error-box', { role: 'alert' });
    const submit = onSubmit
      ? h('button', { type: 'submit', class: danger ? 'danger solid' : 'primary' }, submitLabel) : null;
    const form = h('form', { method: 'dialog', novalidate: false },
      h('header', {}, h('h4', {}, title),
        h('button.ghost.icon.x', { type: 'button', 'aria-label': 'Close', onclick: () => close() }, icon('x'))),
      h('div.content', {}, body, error),
      h('footer', {}, ...actions, h('button', { type: 'button', onclick: () => close() }, onSubmit ? 'Cancel' : 'Close'), submit));
    const dlg = h('dialog', { class: wide ? 'wide' : '' }, form);
    let result;
    function close(value) { result = value; dlg.close(); }
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (!onSubmit) return close();
      error.textContent = '';
      submit.disabled = true;
      try {
        const value = await onSubmit(new FormData(form), form);
        if (value !== false) close(value ?? true);
      } catch (err) {
        error.textContent = err.message || 'Something went wrong';
      } finally {
        submit.disabled = false;
      }
    });
    dlg.addEventListener('close', () => { dlg.remove(); resolve(result); });
    document.body.append(dlg);
    dlg.showModal();
    const first = form.querySelector('.content input:not([type=hidden]):not([type=checkbox]), .content select, .content textarea');
    (first || submit)?.focus();
  });
}

export function confirmDialog(title, text, label = 'Delete') {
  return dialog({ title, body: h('p', {}, text), onSubmit: () => true, submitLabel: label, danger: true });
}

// Field builders for dialog forms
export function field(label, input, hint) {
  return h('label.field', {}, h('span', {}, label), input, hint ? h('span.hint', {}, hint) : null);
}

export function input(name, value, attrs = {}) {
  return h('input', { name, value: value ?? '', autocomplete: 'off', ...attrs });
}

export function select(name, options, value) {
  return h('select', { name }, options.map(([v, label]) => h('option', { value: v, selected: String(v) === String(value ?? '') }, label)));
}

// FormData -> object; empty strings become null
export function formValues(fd, names) {
  const out = {};
  for (const name of names) {
    if (!fd.has(name)) continue;
    const v = fd.get(name);
    out[name] = v === null || v === '' ? null : String(v).trim();
  }
  return out;
}

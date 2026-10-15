import { get, post } from './api.js';

const $ = (id) => document.getElementById(id);

function strength(pw) {
  let score = 0;
  if (pw.length >= 8) score++;
  if (pw.length >= 12) score++;
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) score++;
  if (/\d/.test(pw)) score++;
  if (/[^A-Za-z0-9]/.test(pw)) score++;
  return score;
}

async function submit(form, url, errorBox, toBody) {
  errorBox.textContent = '';
  const button = form.querySelector('button');
  button.disabled = true;
  try {
    await post(url, toBody(new FormData(form)));
    location.href = '/';
  } catch (err) {
    errorBox.textContent = err.message;
  } finally {
    button.disabled = false;
  }
}

async function init() {
  const status = await get('/api/auth/status');
  if (status.user) { location.href = '/'; return; }
  const form = status.needs_setup ? $('setup') : $('login');
  form.classList.remove('hidden');
  form.querySelector('input').focus();

  $('login').addEventListener('submit', (e) => {
    e.preventDefault();
    submit(e.target, '/api/auth/login', $('login-error'), (fd) => ({
      username: fd.get('username'), password: fd.get('password'), remember: fd.get('remember') === 'on' }));
  });

  $('setup').addEventListener('submit', (e) => {
    e.preventDefault();
    submit(e.target, '/api/auth/setup', $('setup-error'), (fd) => ({
      username: fd.get('username'), email: fd.get('email'), password: fd.get('password') }));
  });

  const labels = ['Too short', 'Weak', 'Fair', 'Good', 'Strong', 'Very strong'];
  const colors = ['var(--danger)', 'var(--danger)', 'var(--warn)', 'var(--warn)', 'var(--accent)', 'var(--accent)'];
  $('setup').querySelector('[name=password]').addEventListener('input', (e) => {
    const s = e.target.value.length < 8 ? 0 : strength(e.target.value);
    $('meter').style.width = `${(s / 5) * 100}%`;
    $('meter').style.background = colors[s];
    $('meter-text').textContent = e.target.value ? labels[s] : 'At least 8 characters';
  });
}

init().catch((err) => { $('login').classList.remove('hidden'); $('login-error').textContent = err.message; });

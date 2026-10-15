import { get, post } from './api.js';

const $ = (id) => document.getElementById(id);
const form = $('login');
const f = form.elements;
const submit = $('submit');
let mode = 'login'; // or 'setup'

$('host').textContent = location.hostname;

function showError(message, field) {
  $('error-text').textContent = message;
  $('error').hidden = !message;
  for (const el of [f.username, f.password, f.email]) el.removeAttribute('aria-invalid');
  if (!message) return;
  if (field) field.setAttribute('aria-invalid', 'true');
  form.classList.remove('shake');
  void form.offsetWidth; // restart the animation
  form.classList.add('shake');
}

function setBusy(busy) {
  submit.dataset.state = busy ? 'busy' : '';
  submit.disabled = busy;
  const idle = mode === 'setup' ? 'Create admin' : 'Continue';
  $('submit-text').textContent = busy ? (mode === 'setup' ? 'Creating…' : 'Signing in…') : idle;
}

$('pw-toggle').addEventListener('click', () => {
  const show = f.password.type === 'password';
  f.password.type = show ? 'text' : 'password';
  $('pw-toggle').setAttribute('aria-pressed', String(show));
  $('pw-toggle').setAttribute('aria-label', show ? 'Hide password' : 'Show password');
  $('pw-toggle').querySelector('use').setAttribute('href', show ? '#pg-eye-off' : '#pg-eye');
  f.password.focus();
});

for (const type of ['keydown', 'keyup']) {
  f.password.addEventListener(type, (e) => { $('caps').hidden = !e.getModifierState?.('CapsLock'); });
}
f.password.addEventListener('blur', () => { $('caps').hidden = true; });

// Strength hint while creating the first admin
const LEVELS = [['Too short', 'var(--danger)'], ['Weak', 'var(--danger)'], ['Fair', 'var(--warn)'], ['Good', 'var(--warn)'], ['Strong', 'var(--ok)'], ['Very strong', 'var(--ok)']];
f.password.addEventListener('input', () => {
  if (mode !== 'setup') return;
  const pw = f.password.value;
  const score = pw.length < 8 ? 0 : [pw.length >= 8, pw.length >= 12, /[a-z]/.test(pw) && /[A-Z]/.test(pw), /\d/.test(pw), /[^A-Za-z0-9]/.test(pw)].filter(Boolean).length;
  $('meter').style.width = `${(score / 5) * 100}%`;
  $('meter').style.background = LEVELS[score][1];
});

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  if (submit.dataset.state === 'busy') return;
  showError('');
  const required = mode === 'setup' ? [f.username, f.email, f.password] : [f.username, f.password];
  const missing = required.find((i) => !i.value.trim());
  if (missing) { showError(`Enter your ${missing.name}.`, missing); missing.focus(); return; }
  if (mode === 'setup' && f.password.value.length < 8) { showError('Use at least 8 characters.', f.password); return; }
  setBusy(true);
  try {
    const body = { username: f.username.value, password: f.password.value };
    if (mode === 'setup') body.email = f.email.value;
    else body.remember = true;
    await post(mode === 'setup' ? '/api/auth/setup' : '/api/auth/login', body);
    remember('local');
    location.replace('/');
  } catch (err) {
    setBusy(false);
    showError(err.message, err.status === 401 ? f.password : null);
    f.password.select();
  }
});

// Single sign-on comes first when configured; the password form waits behind
// "Use a local account". A browser that last signed in locally opens it at once,
// so password managers can fill the fields.
const SSO_ERRORS = {
  sso_denied: (n) => `Your ${n} account doesn't have access to lattice. Ask an admin to add you to one of its groups.`,
  sso_state: () => 'That sign-in expired or was started in another browser. Try again.',
  sso_failed: (n) => `Signing in with ${n} didn't work. Try again; if it keeps failing, the lattice log says why.`,
  sso_unavailable: (n) => `Can't reach ${n} right now. Try again in a moment.`,
  sso_off: () => "Single sign-on isn't set up on this server.",
};
const remember = (how) => { try { localStorage.setItem('lattice.login', how); } catch { /* private mode */ } };
const remembered = () => { try { return localStorage.getItem('lattice.login'); } catch { return null; } };

function showLocal(open) {
  $('step-password').hidden = !open;
  submit.hidden = !open;
  $('local-or').setAttribute('aria-expanded', String(open));
  $('local-or').classList.toggle('open', open);
  $('local-or-text').textContent = open ? 'or use a local account' : 'Use a local account';
}

function showSetup() {
  mode = 'setup';
  $('title').textContent = 'Set up lattice';
  $('lede').textContent = 'Create the first admin account.';
  $('email-row').classList.remove('hidden');
  $('meter-row').classList.remove('hidden');
  f.password.autocomplete = 'new-password';
  $('foot').textContent = 'You can add more people and single sign-on afterwards.';
  setBusy(false);
  f.username.focus();
}

(async () => {
  const params = new URLSearchParams(location.search);
  const error = params.get('error');
  const openLocal = params.has('local');
  if (error || openLocal) history.replaceState(null, '', '/login');
  let cfg = { sso: null, local: true, needs_setup: false };
  try { cfg = await get('/api/auth/config'); } catch { /* show the password form */ }
  if (cfg.needs_setup) { showSetup(); return; }
  setBusy(false);
  const name = cfg.sso?.name || 'SSO';
  if (cfg.sso) {
    $('sso').hidden = false;
    $('sso-text').textContent = `Continue with ${name}`;
    submit.classList.remove('primary'); // one primary action on the page
    $('foot').textContent = cfg.local ? `Access is managed in ${name}. Local accounts are a fallback.` : `Access is managed in ${name}.`;
    if (cfg.local) {
      $('local-or').hidden = false;
      showLocal(openLocal || remembered() === 'local');
      $('local-or').addEventListener('click', () => {
        if ($('local-or').classList.contains('open')) return;
        showLocal(true);
        f.username.focus();
      });
    } else {
      $('step-password').hidden = true;
      submit.hidden = true;
    }
    $('sso-btn').addEventListener('click', () => {
      remember('sso');
      $('sso-btn').dataset.state = 'busy';
      $('sso-text').textContent = `Opening ${name}…`;
    });
  } else {
    f.username.focus();
  }
  if (error) showError((SSO_ERRORS[error] || SSO_ERRORS.sso_failed)(name));
})();

// Back from the provider with the back button: the button works again
window.addEventListener('pageshow', (e) => {
  if (e.persisted && $('sso-btn').dataset.state) {
    delete $('sso-btn').dataset.state;
    $('sso-text').textContent = $('sso-text').textContent.replace(/^Opening (.*)…$/, 'Continue with $1');
  }
});

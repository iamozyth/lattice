// Fetch wrapper: JSON in and out, the CSRF header on every write, 401 -> login page.
export class ApiError extends Error {
  constructor(message, status, data) { super(message); this.status = status; this.data = data; }
}

export async function api(method, url, body) {
  const opts = { method, headers: { Accept: 'application/json' }, credentials: 'same-origin' };
  if (method !== 'GET') opts.headers['X-Requested-With'] = 'lattice';
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(url, opts);
  } catch {
    throw new ApiError('Lattice is not reachable. Check your connection.', 0);
  }
  if (res.status === 401 && !url.startsWith('/api/auth/login')) {
    location.href = '/login';
    throw new ApiError('Session expired', 401);
  }
  if (res.status === 204) return null;
  let data = null;
  try { data = await res.json(); } catch { /* empty or non-JSON body */ }
  if (!res.ok) {
    const message = data?.error || data?.message
      || (res.status === 429 ? 'Too many requests. Wait a moment and try again.' : `Request failed (${res.status})`);
    throw new ApiError(typeof message === 'string' ? message : 'Invalid input', res.status, data);
  }
  return data;
}

export const get = (url) => api('GET', url);
export const post = (url, body = {}) => api('POST', url, body);
export const put = (url, body) => api('PUT', url, body);
export const del = (url) => api('DELETE', url);

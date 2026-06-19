/* Auth state — JWT validation, login, logout, role visibility.
   Phase 15.A: Removed overlay logic (login is now a separate page).
   Cookie is set by server (Set-Cookie); JWT also stored in sessionStorage
   for API Authorization headers. */
import { api } from './api.js';
import { ws } from './ws-client.js';

let userRole = null;

function checkAuth() {
  const token = api.getToken();
  if (!token) { redirectToLogin(); return; }
  try {
    const payload = JSON.parse(atob(token.split('.')[1]));
    if (payload.exp * 1000 < Date.now()) {
      api.clearToken();
      redirectToLogin();
      return;
    }
    userRole = payload.role || 'observer';
  } catch {
    api.clearToken();
    redirectToLogin();
    return;
  }
  applyRoleVisibility();
  ws.connect(token);
}

function redirectToLogin() {
  window.location.href = '/login';
}

function applyRoleVisibility() {
  const adminOnly = ['agents', 'plugins', 'audit'];
  if (userRole === 'admin') return;
  adminOnly.forEach(p => {
    const nav = document.querySelector(`#nav a[data-page="${p}"]`);
    if (nav) nav.style.display = userRole === 'agent' ? '' : 'none';
  });
}

async function login(username, password) {
  const res = await api.post('/auth/login', { username, password });
  api.setToken(res.token);
  userRole = res.role;
  applyRoleVisibility();
  ws.connect(res.token);
}

async function logout() {
  ws.disconnect();
  api.clearToken();
  userRole = null;
  try { await api.post('/auth/logout', {}); } catch { /* ignore */ }
  redirectToLogin();
}

export const auth = { checkAuth, login, logout, getUserRole: () => userRole };

/* App entry point — SPA router + nav handling (auth in auth.js) */
import { auth } from './auth.js';
import { ws } from './ws-client.js';
import { notifUI } from './notifications-ui.js';

let currentPage = null;
const pages = {};

async function loadPageModule(name) {
  if (!pages[name]) pages[name] = await import(`./pages/${name}.js`);
  return pages[name];
}

async function navigate(page) {
  if (currentPage) {
    const mod = await loadPageModule(currentPage);
    mod.unmount?.();
  }
  document.querySelectorAll('.page').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('#nav a').forEach(a => a.classList.remove('active'));
  const pageEl = document.getElementById(page);
  const navEl = document.querySelector(`#nav a[data-page="${page}"]`);
  if (pageEl) pageEl.classList.add('active');
  if (navEl) navEl.classList.add('active');
  currentPage = page;
  const mod = await loadPageModule(page);
  mod.mount(pageEl);
  location.hash = page;
}

function init() {
  document.querySelectorAll('#nav a[data-page]').forEach(a => {
    a.addEventListener('click', e => { e.preventDefault(); navigate(a.dataset.page); });
  });
  window.addEventListener('hashchange', () => {
    const page = location.hash.slice(1) || 'overview';
    if (page !== currentPage) navigate(page);
  });
  document.getElementById('btn-logout')?.addEventListener('click', () => {
    auth.logout();
  });
  auth.checkAuth();
  notifUI.init();
  wireConnStatus();
  navigate(location.hash.slice(1) || 'overview');
}

const STATUS_LABELS = { connected:'Connected', reconnecting:'Reconnecting…', offline:'Offline' };
function wireConnStatus() {
  ws.onStatus(s => {
    const dot = document.getElementById('conn-dot');
    const lbl = document.getElementById('conn-label');
    const wrap = document.getElementById('conn-status');
    if (dot) dot.className = `conn-dot ${s}`;
    if (lbl) lbl.textContent = STATUS_LABELS[s] || s;
    if (wrap) wrap.className = `conn-status ${s}`;
  });
}

export const app = { init, navigate, getUserRole: auth.getUserRole };

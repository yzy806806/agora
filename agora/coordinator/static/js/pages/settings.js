/* Settings page — configure Agora runtime settings.
Categories: GitHub, LLM, Agents, Daemon, Git, Docs.
Secrets are masked (sk-***xyz) until user clicks edit. */
import { api } from '../api.js';

let currentSettings = null, schema = null;

export function mount(c) {
  c.innerHTML = `
    <div class="settings-header" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
      <h2>⚙️ Settings</h2>
      <button id="btn-save-settings" class="btn btn-primary" disabled>Save Changes</button>
    </div>
    <div id="settings-content"><div class="loading">Loading…</div></div>
  `;
  loadSettings();
  document.getElementById('btn-save-settings').addEventListener('click', saveSettings);
}
export function unmount() {}

async function loadSettings() {
  try {
    const [data, sch] = await Promise.all([
      api.get('/settings'),
      api.get('/settings/schema'),
    ]);
    currentSettings = data;
    schema = sch;
    renderSettings(data);
  } catch (e) {
    document.getElementById('settings-content').innerHTML =
      `<div class="error">Failed to load settings: ${e.message}</div>`;
  }
}

function renderSettings(data) {
  const el = document.getElementById('settings-content');
  let html = '';
  for (const cat of schema.categories) {
    const catData = data[cat.id];
    if (!catData) continue;
    html += `<div class="card settings-category">
      <h3>${cat.icon} ${cat.label}</h3>
      <div class="settings-fields">`;
    for (const [key, field] of Object.entries(catData.settings)) {
      html += renderField(key, field);
    }
    html += `</div></div>`;
  }
  el.innerHTML = html;
  wireInputs();
}

function renderField(key, field) {
  const s = field.schema;
  const val = field.value ?? s.default ?? '';
  const isSecret = s.type === 'secret';
  const inputId = `setting-${key}`;

  let input;
  if (s.type === 'boolean') {
    input = `<label class="toggle">
      <input type="checkbox" id="${inputId}" data-key="${key}"
             ${val ? 'checked' : ''} />
      <span class="toggle-slider"></span>
    </label>`;
  } else if (s.type === 'number') {
    input = `<input type="number" id="${inputId}" data-key="${key}"
               value="${val}" class="setting-input" />`;
  } else if (isSecret) {
    input = `<div class="secret-field">
      <input type="password" id="${inputId}" data-key="${key}"
             placeholder="${val || 'Not set'}" class="setting-input secret" />
      <button class="btn btn-sm btn-ghost" data-toggle-secret="${inputId}">👁</button>
    </div>`;
  } else {
    input = `<input type="text" id="${inputId}" data-key="${key}"
               value="${val}" class="setting-input" />`;
  }

  return `<div class="setting-row" data-key="${key}">
    <div class="setting-label">
      <label for="${inputId}">${s.label}</label>
      ${s.description ? `<span class="setting-desc">${s.description}</span>` : ''}
    </div>
    <div class="setting-control">${input}</div>
  </div>`;
}

function wireInputs() {
  // Toggle secret visibility
  document.querySelectorAll('[data-toggle-secret]').forEach(btn => {
    btn.addEventListener('click', () => {
      const inputId = btn.dataset.toggleSecret;
      const input = document.getElementById(inputId);
      input.type = input.type === 'password' ? 'text' : 'password';
    });
  });
  // Track changes
  document.querySelectorAll('[data-key]').forEach(input => {
    input.addEventListener('input', () => {
      document.getElementById('btn-save-settings').disabled = false;
    });
    input.addEventListener('change', () => {
      document.getElementById('btn-save-settings').disabled = false;
    });
  });
}

async function saveSettings() {
  const btn = document.getElementById('btn-save-settings');
  btn.disabled = true;
  btn.textContent = 'Saving…';

  const updates = {};
  document.querySelectorAll('[data-key]').forEach(input => {
    const key = input.dataset.key;
    let value;
    if (input.type === 'checkbox') {
      value = input.checked;
    } else if (input.type === 'number') {
      value = input.value ? Number(input.value) : null;
    } else {
      value = input.value || null;
    }
    // Skip empty secret fields (user didn't change)
    if (input.classList.contains('secret') && !value) return;
    updates[key] = value;
  });

  try {
    const result = await api.put('/settings', { settings: updates });
    showToast(`✅ Saved ${result.count} settings`);
    await loadSettings(); // refresh to show masked values
  } catch (e) {
    showToast(`❌ Save failed: ${e.message}`);
    btn.disabled = false;
    btn.textContent = 'Save Changes';
  }
}

function showToast(msg) {
  let t = document.getElementById('settings-toast');
  if (!t) {
    t = document.createElement('div');
    t.id = 'settings-toast';
    t.style.cssText = 'position:fixed;bottom:20px;right:20px;padding:12px 20px;border-radius:8px;background:#1a1a2e;color:#fff;z-index:9999;transition:opacity 0.3s';
    document.body.appendChild(t);
  }
  t.textContent = msg;
  t.style.opacity = '1';
  setTimeout(() => { t.style.opacity = '0'; }, 3000);
}

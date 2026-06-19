/* Agent Management Page — tabs, approve/reject, suspend, inline config.
Phase 13.2b: uses AGENT_STATUS canonical type
Phase 15.C: added "Pending" tab for approval workflow */
import { api } from '../api.js';
import { ws } from '../ws-client.js';
let unsubs = [];
let currentTab = 'all';

export function mount(c) {
  c.innerHTML = `<h2>Agent Management</h2>
    <div style="margin-bottom:12px;display:flex;gap:8px;align-items:center">
      <div class="tab-bar">
        <button class="tab active" data-tab="all">All</button>
        <button class="tab" data-tab="pending">Pending</button>
        <button class="tab" data-tab="approved">Approved</button>
        <button class="tab" data-tab="rejected">Rejected</button>
      </div>
      <input id="agent-search" placeholder="Search..." style="width:200px;margin-left:auto">
      <button id="btn-refresh" class="secondary">Refresh</button>
    </div>
    <table><thead><tr><th>Name</th><th>Status</th><th>Role</th><th>TPM</th><th>Conc</th><th>Approval</th><th>Actions</th></tr></thead>
    <tbody id="agent-tbody"></tbody></table>
    <div id="token-modal" class="modal-overlay hidden"><div class="modal"><h3>New Token</h3>
      <pre id="token-value" style="word-break:break-all"></pre>
      <div class="actions"><button class="secondary" onclick="this.closest('.modal-overlay').classList.add('hidden')">Close</button></div>
    </div></div>`;
  // Tab switching
  c.querySelectorAll('.tab').forEach(b => b.onclick = () => {
    c.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    b.classList.add('active');
    currentTab = b.dataset.tab;
    load();
  });
  document.getElementById('btn-refresh').onclick = load;
  document.getElementById('agent-search').oninput = load;
  load(); subWS();
}
export function unmount() { unsubs.forEach(f => f()); unsubs = []; }

async function load() {
  const tb = document.getElementById('agent-tbody'); if (!tb) return;
  try {
    const agents = await api.get('/admin/agents');
    const q = (document.getElementById('agent-search')?.value||'').toLowerCase();
    let filtered = agents.filter(a => a.name.toLowerCase().includes(q) || a.agent_id.toLowerCase().includes(q));
    // Tab filter
    if (currentTab !== 'all') {
      filtered = filtered.filter(a => (a.approval_status||'pending') === currentTab);
    }
    tb.innerHTML = filtered.map(a => `<tr data-id="${a.agent_id}">
      <td>${esc(a.name)} <span style="color:#94a3b8;font-size:11px">${a.agent_id.slice(0,8)}</span></td>
      <td><span class="badge badge-${a.is_online?'online':'offline'}">${a.is_online?'on':'off'}</span></td>
      <td>${a.role||'agent'}</td>
      <td><input class="inline" data-f="tpm_limit" type="number" value="${a.tpm_limit||10000}" style="width:70px"></td>
      <td><input class="inline" data-f="max_concurrent_tasks" type="number" value="${a.max_concurrent_tasks||2}" style="width:50px"></td>
      <td><span class="badge badge-${a.approval_status||'pending'}">${a.approval_status||'pending'}</span></td>
      <td>${btns(a)}</td></tr>`).join('');
    tb.querySelectorAll('[data-act]').forEach(b => b.onclick = () => act(b.dataset.act, b.dataset.id, b.closest('tr')));
  } catch (e) { tb.innerHTML = `<tr><td colspan="7">Error: ${e.message}</td></tr>`; }
}

function btns(a) {
  const id = a.agent_id, s = a.approval_status; let r = '';
  if (s==='pending') r += `<button class="btn-sm" data-act="approve" data-id="${id}">Approve</button><button class="danger btn-sm" data-act="reject" data-id="${id}">Reject</button>`;
  if (s==='approved') r += `<button class="danger btn-sm" data-act="suspend" data-id="${id}">Suspend</button>`;
  if (s==='suspended') r += `<button class="btn-sm" data-act="approve" data-id="${id}">Activate</button>`;
  r += `<button class="secondary btn-sm" data-act="token" data-id="${id}">Token</button>`;
  r += `<button class="btn-sm" data-act="save" data-id="${id}">Save</button>`;
  return r;
}

async function act(action, id, row) {
  try {
    if (action==='save') {
      const body = {};
      row.querySelectorAll('.inline').forEach(i => body[i.dataset.f] = Number(i.value));
      await api.put(`/admin/agents/${id}/config`, body); load();
    } else if (action==='token') {
      const r = await api.post(`/admin/agents/${id}/token`);
      document.getElementById('token-value').textContent = r.agent_token;
      document.getElementById('token-modal').classList.remove('hidden');
    } else { await api.post(`/admin/agents/${id}/${action}`); load(); }
  } catch (e) { alert(`Failed: ${e.message}`); }
}

function subWS() {
  ws.subscribe(['agents']);
  unsubs.push(ws.on('AGENT_STATUS', load));
}
function esc(s) { return String(s).replace(/[<>&"']/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;',"'":'&#39;'}[c])); }

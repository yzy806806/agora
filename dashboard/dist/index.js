// Agora Dashboard — multi-role deliberation view
// Renders motion list, motion detail with messages, and new motion form.

(function() {
  const API = '/api/plugins/agora';
  let currentView = 'list';
  let currentMotionId = null;

  async function api(path, opts = {}) {
    const token = window.__HERMES_SESSION_TOKEN__ || '';
    const res = await fetch(API + path, {
      ...opts,
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token, ...(opts.headers || {}) },
    });
    if (!res.ok) throw new Error(`API ${path}: ${res.status}`);
    return res.json();
  }

  async function render(root) {
    if (currentView === 'list') return renderList(root);
    if (currentView === 'detail') return renderDetail(root, currentMotionId);
    if (currentView === 'new') return renderNew(root);
  }

  async function renderList(root) {
    const [statsRes, motionsRes] = await Promise.all([
      api('/stats').catch(() => ({ total: 0, active: 0, closed: 0, adopted: 0, rejected: 0 })),
      api('/motions?status=all&limit=50'),
    ]);

    const motions = motionsRes.motions || [];
    const s = statsRes;

    root.innerHTML = `
      <div class="agora-container">
        <div class="agora-header">
          <h1>🏛️ Agora — Deliberation</h1>
          <button class="agora-new-btn" data-action="new">+ New Discussion</button>
        </div>
        <div class="agora-stats">
          <div class="agora-stat"><div class="num">${s.total}</div><div class="label">Total</div></div>
          <div class="agora-stat"><div class="num">${s.active}</div><div class="label">Active</div></div>
          <div class="agora-stat"><div class="num" style="color:#4ade80">${s.adopted}</div><div class="label">Adopted</div></div>
          <div class="agora-stat"><div class="num" style="color:#f87171">${s.rejected}</div><div class="label">Rejected</div></div>
        </div>
        <div class="agora-motion-list" style="margin-top:1.5rem">
          ${motions.length === 0 ? '<div class="agora-empty">No discussions yet. Click "New Discussion" to start one.</div>' :
            motions.map(m => `
              <div class="agora-motion-card" data-action="detail" data-id="${m.id}">
                <div class="title">${escapeHtml(m.title)}</div>
                <div class="meta">
                  <span class="agora-badge ${m.status === 'closed' ? (m.decision || 'closed') : 'discussing'}">${m.status === 'closed' ? m.decision || 'closed' : 'discussing'}</span>
                  <span>Round ${m.current_round}/${m.max_rounds}</span>
                  <span>${m.source === 'user' ? '👤' : '🤖'} ${m.source}</span>
                  <span>${formatDate(m.created_at)}</span>
                </div>
              </div>
            `).join('')
          }
        </div>
      </div>
    `;

    root.querySelectorAll('[data-action="detail"]').forEach(el => {
      el.onclick = () => { currentView = 'detail'; currentMotionId = el.dataset.id; render(root); };
    });
    root.querySelector('[data-action="new"]').onclick = () => { currentView = 'new'; render(root); };
  }

  async function renderDetail(root, motionId) {
    try {
      const m = await api(`/motions/${motionId}`);
      const messages = m.messages || [];

      root.innerHTML = `
        <div class="agora-container">
          <div class="agora-back" data-action="back">← Back to list</div>
          <div class="agora-motion-detail">
            <h2 style="margin:0 0 0.5rem">${escapeHtml(m.title)}</h2>
            <div class="meta" style="font-size:0.8rem;opacity:0.7;margin-bottom:1rem">
              <span class="agora-badge ${m.status === 'closed' ? (m.decision || 'closed') : 'discussing'}">${m.status === 'closed' ? m.decision || 'closed' : 'discussing'}</span>
              <span>Round ${m.current_round}/${m.max_rounds}</span>
              <span>${m.source}</span>
              <span>${formatDate(m.created_at)}</span>
            </div>
            ${m.description ? `<p style="opacity:0.8;margin-bottom:1rem">${escapeHtml(m.description)}</p>` : ''}
            ${m.status === 'closed' && m.action_items ? `
              <div class="agora-action-items">
                <h3 style="font-size:0.9rem;margin-bottom:0.5rem">Action Items</h3>
                ${m.action_items.map(ai => `<div class="agora-action-item">${escapeHtml(ai)}</div>`).join('')}
              </div>
            ` : ''}
            <h3 style="font-size:0.9rem;margin:1.5rem 0 0.5rem">Discussion (${messages.length} messages)</h3>
            ${messages.map(msg => `
              <div class="agora-message">
                <span class="role">${msg.role}</span>
                <span class="round-tag">R${msg.round_num}</span>
                <span class="stance ${msg.stance}">${msg.stance}</span>
                <div class="content">${escapeHtml(msg.content)}</div>
              </div>
            `).join('')}
          </div>
        </div>
      `;

      root.querySelector('[data-action="back"]').onclick = () => { currentView = 'list'; render(root); };
    } catch (e) {
      root.innerHTML = `<div class="agora-container"><div class="agora-back" data-action="back">← Back</div><p>Error: ${escapeHtml(e.message)}</p></div>`;
      root.querySelector('[data-action="back"]').onclick = () => { currentView = 'list'; render(root); };
    }
  }

  async function renderNew(root) {
    root.innerHTML = `
      <div class="agora-container">
        <div class="agora-back" data-action="back">← Back to list</div>
        <h2 style="margin:0 0 1rem">New Discussion</h2>
        <div class="agora-new-form">
          <input type="text" id="agora-title" placeholder="Discussion topic..." />
          <textarea id="agora-desc" rows="4" placeholder="Description (optional)"></textarea>
          <label>Participants: <input type="text" id="agora-participants" value="architect,developer,reviewer" style="width:300px" /></label>
          <label>Rounds: <input type="number" id="agora-rounds" value="3" min="1" max="10" style="width:80px" /></label>
          <button id="agora-submit">Start Discussion</button>
        </div>
      </div>
    `;

    root.querySelector('[data-action="back"]').onclick = () => { currentView = 'list'; render(root); };
    root.querySelector('#agora-submit').onclick = async () => {
      const title = root.querySelector('#agora-title').value.trim();
      if (!title) return;
      const desc = root.querySelector('#agora-desc').value.trim();
      const parts = root.querySelector('#agora-participants').value.split(',').map(s => s.trim()).filter(Boolean);
      const rounds = parseInt(root.querySelector('#agora-rounds').value) || 3;

      try {
        await api('/motions', {
          method: 'POST',
          body: JSON.stringify({ title, description: desc, rounds, participants: parts }),
        });
        currentView = 'list';
        render(root);
      } catch (e) {
        alert('Failed: ' + e.message);
      }
    };
  }

  function escapeHtml(s) {
    if (!s) return '';
    return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  function formatDate(iso) {
    if (!iso) return '';
    try { return new Date(iso).toLocaleString(); } catch { return iso; }
  }

  // Register with Hermes dashboard plugin system
  window.__AGORA_PLUGIN__ = { render };
})();

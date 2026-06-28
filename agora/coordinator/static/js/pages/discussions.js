/* Discussions page — real-time viewer with WS subscription.
Phase 13.2b: uses DISCUSSION_UPDATE canonical type
(backward-compat via ws-client alias from legacy types).
+ Dashboard discussion creation: New Discussion button. */
import { api } from '../api.js';
import { ws } from '../ws-client.js';

let currentMotion = null, unsubs = [];
const ROLE_COLORS = {proposer:'#f59e0b',participant:'#3b82f6',reviewer:'#8b5cf6',moderator:'#ef4444',architect:'#f59e0b',developer:'#3b82f6'};
const $ = id => document.getElementById(id);

export function mount(c) {
  c.innerHTML = `<h2>Discussion Detail</h2>
    <div class="card" style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <label>Motion: </label>
      <select id="motion-select"><option value="">-- select --</option></select>
      <span id="motion-status" style="margin-left:12px"></span>
      <button id="btn-new-discussion" class="primary" style="margin-left:auto">+ New Discussion</button>
    </div>
    <div id="timeline" style="max-height:500px;overflow-y:auto"></div>
    <div id="vote-summary" class="card" style="margin-top:12px"></div>
    <!-- New Discussion Form Modal -->
    <div id="new-disc-modal" class="modal-overlay hidden">
      <div class="modal" style="max-width:520px">
        <h3>Start a Discussion</h3>
        <form id="new-disc-form">
          <div style="margin-bottom:8px">
            <label>Title <span style="color:var(--danger)">*</span></label>
            <input type="text" id="nd-title" required style="width:100%;padding:6px" placeholder="e.g. Refactor storage layer">
          </div>
          <div style="margin-bottom:8px">
            <label>Description / Context</label>
            <textarea id="nd-desc" rows="4" style="width:100%;padding:6px" placeholder="What should the team discuss? Any context or constraints?"></textarea>
          </div>
          <div style="margin-bottom:8px;display:flex;gap:12px">
            <div style="flex:1">
              <label>Rounds</label>
              <input type="number" id="nd-rounds" value="3" min="1" max="10" style="width:100%;padding:6px">
            </div>
            <div style="flex:1">
              <label>Voting Method</label>
              <select id="nd-voting" style="width:100%;padding:6px">
                <option value="unanimous">Unanimous</option>
                <option value="majority" selected>Majority</option>
                <option value="consensus">Consensus</option>
              </select>
            </div>
          </div>
          <div class="actions">
            <button type="button" class="secondary" id="nd-cancel">Cancel</button>
            <button type="submit">Create & Start</button>
          </div>
        </form>
      </div>
    </div>`;
  $('motion-select').onchange = onSelectMotion;
  $('btn-new-discussion').onclick = () => $('new-disc-modal').classList.remove('hidden');
  $('new-disc-modal').onclick = e => {
    if (e.target.id === 'new-disc-modal') e.target.classList.add('hidden');
  };
  $('nd-cancel').onclick = () => $('new-disc-modal').classList.add('hidden');
  $('new-disc-form').onsubmit = onCreateDiscussion;
  loadMotionList(); subscribeWS();
}

export function unmount() { unsubs.forEach(fn => fn()); unsubs = []; currentMotion = null; }

async function loadMotionList() {
  const m = await api.get('/motions?limit=100');
  const s = $('motion-select'); if (!s) return;
  const list = m.motions || m || [];
  s.innerHTML = '<option value="">-- select --</option>' +
    list.map(x => `<option value="${x.id}">${x.title} (${x.status})</option>`).join('');
}

async function onSelectMotion() {
  const mid = $('motion-select')?.value; if (!mid) return;
  currentMotion = mid;
  await Promise.all([loadTimeline(mid), loadVotes(mid)]);
}

async function loadTimeline(mid) {
  const tl = await api.get(`/discussions/${mid}/timeline`);
  const el = $('timeline'); if (!el) return;
  el.innerHTML = (tl || []).map(renderEntry).join('');
  el.scrollTop = el.scrollHeight;
}

async function loadVotes(mid) {
  const v = await api.get(`/motions/${mid}/votes`).catch(() => null);
  const el = $('vote-summary'); if (!el) return;
  const sum = v?.summary || v;
  el.innerHTML = sum ? `<h3>Vote Summary</h3><pre>${JSON.stringify(sum,null,2)}</pre>` : '';
}

function renderEntry(x) {
  const c = ROLE_COLORS[x.role] || '#94a3b8', r = x.round_num ? ` [R${x.round_num}]` : '';
  return `<div class="event"><span class="time">${x.time||''}</span> ` +
    `<span class="detail">${r} <span style="color:${c}">${x.agent_id||''}</span>: ${x.content}</span></div>`;
}

async function onCreateDiscussion(e) {
  e.preventDefault();
  const title = $('nd-title').value.trim();
  if (!title) return;
  const body = {
    title,
    description: $('nd-desc').value.trim(),
    rounds: parseInt($('nd-rounds').value) || 3,
    voting_method: $('nd-voting').value,
  };
  try {
    const motion = await api.post('/motions', body);
    // Auto-start the discussion
    await api.post(`/motions/${motion.id}/start`);
    $('new-disc-modal').classList.add('hidden');
    $('new-disc-form').reset();
    // Select the new motion
    await loadMotionList();
    $('motion-select').value = motion.id;
    currentMotion = motion.id;
    await Promise.all([loadTimeline(motion.id), loadVotes(motion.id)]);
  } catch (err) {
    alert(`Create discussion failed: ${err.message}`);
  }
}

function subscribeWS() {
  // Phase 13.2b: canonical DISCUSSION_UPDATE catches all discussion events
  unsubs.push(ws.on('DISCUSSION_UPDATE', p => {
    if (p.motion_id && p.motion_id !== currentMotion) return;
    if (p.content) {
      const el = $('timeline'); if (!el) return;
      const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
      el.insertAdjacentHTML('beforeend',
        renderEntry({time:p.timestamp,agent_id:p.agent_id,content:p.content,round_num:p.round}));
      if (atBottom) el.scrollTop = el.scrollHeight;
    }
    if (p.status) {
      const el = $('motion-status'); if (el) el.textContent = p.status;
    }
    if (p.vote) loadVotes(currentMotion);
  }));
}

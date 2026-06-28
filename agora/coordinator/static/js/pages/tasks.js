/* Task Kanban Page — fetch graphs, render board, WS real-time updates.
Phase 13.2b: uses TASK_UPDATE canonical type
(backward-compat via ws-client alias from TASK_STATUS etc).
+ Dashboard task creation: New Task / New Graph buttons. */
import { api } from '../api.js';
import { ws } from '../ws-client.js';
import { KanbanBoard } from '../components/kanban-board.js';

let board = null, unsubTask = null, currentGraphId = null;
const $ = id => document.getElementById(id);

export function mount(container) {
  container.innerHTML = `
    <h2>Task Board</h2>
    <div style="margin-bottom:12px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <select id="graph-select"><option value="">All Tasks</option></select>
      <button id="btn-refresh" class="secondary">Refresh</button>
      <button id="btn-new-graph" class="primary" style="margin-left:auto">+ New Graph</button>
      <button id="btn-new-task" class="primary">+ New Task</button>
    </div>
    <div id="kanban-container"></div>
    <div id="task-modal" class="modal-overlay hidden"><div class="modal" id="task-detail"></div></div>
    <!-- New Task Form Modal -->
    <div id="new-task-modal" class="modal-overlay hidden">
      <div class="modal" style="max-width:520px">
        <h3>Create Task</h3>
        <form id="new-task-form">
          <div style="margin-bottom:8px">
            <label>Title <span style="color:var(--danger)">*</span></label>
            <input type="text" id="nt-title" required style="width:100%;padding:6px">
          </div>
          <div style="margin-bottom:8px">
            <label>Description</label>
            <textarea id="nt-desc" rows="3" style="width:100%;padding:6px"></textarea>
          </div>
          <div style="margin-bottom:8px;display:flex;gap:12px">
            <div style="flex:1">
              <label>Assign To</label>
              <select id="nt-assign" style="width:100%;padding:6px">
                <option value="">— unassigned —</option>
                <option value="architect">architect</option>
                <option value="developer">developer</option>
                <option value="reviewer">reviewer</option>
              </select>
            </div>
            <div style="flex:1">
              <label>Graph</label>
              <select id="nt-graph" style="width:100%;padding:6px">
                <option value="">— auto create —</option>
              </select>
            </div>
          </div>
          <div style="margin-bottom:8px">
            <label>Priority</label>
            <select id="nt-priority" style="width:100%;padding:6px">
              <option value="normal">Normal</option>
              <option value="low">Low</option>
              <option value="high">High</option>
              <option value="critical">Critical</option>
            </select>
          </div>
          <div class="actions">
            <button type="button" class="secondary" id="nt-cancel">Cancel</button>
            <button type="submit">Create</button>
          </div>
        </form>
      </div>
    </div>
    <!-- New Graph Form Modal -->
    <div id="new-graph-modal" class="modal-overlay hidden">
      <div class="modal" style="max-width:440px">
        <h3>Create Task Graph</h3>
        <form id="new-graph-form">
          <div style="margin-bottom:8px">
            <label>Graph ID (optional)</label>
            <input type="text" id="ng-id" placeholder="auto-generated" style="width:100%;padding:6px">
          </div>
          <div style="margin-bottom:8px">
            <label>Linked Motion (optional)</label>
            <input type="text" id="ng-motion" placeholder="motion-xxxx" style="width:100%;padding:6px">
          </div>
          <div class="actions">
            <button type="button" class="secondary" id="ng-cancel">Cancel</button>
            <button type="submit">Create</button>
          </div>
        </form>
      </div>
    </div>`;
  $('graph-select').onchange = loadTasks;
  $('btn-refresh').onclick = loadTasks;
  $('btn-new-task').onclick = () => {
    populateGraphSelect();
    $('new-task-modal').classList.remove('hidden');
  };
  $('btn-new-graph').onclick = () => $('new-graph-modal').classList.remove('hidden');
  $('task-modal').onclick = e => {
    if (e.target.id === 'task-modal') e.target.classList.add('hidden');
  };
  $('new-task-modal').onclick = e => {
    if (e.target.id === 'new-task-modal') e.target.classList.add('hidden');
  };
  $('new-graph-modal').onclick = e => {
    if (e.target.id === 'new-graph-modal') e.target.classList.add('hidden');
  };
  $('nt-cancel').onclick = () => $('new-task-modal').classList.add('hidden');
  $('ng-cancel').onclick = () => $('new-graph-modal').classList.add('hidden');
  $('new-task-form').onsubmit = onCreateTask;
  $('new-graph-form').onsubmit = onCreateGraph;
  board = new KanbanBoard(document.getElementById('kanban-container'), {onCardClick: showDetail});
  loadGraphs(); loadTasks(); subscribeWS();
}

export function unmount() {
  if (unsubTask) { unsubTask(); unsubTask = null; }
  if (board) { board.destroy(); board = null; }
}

async function populateGraphSelect() {
  try {
    const data = await api.get('/task-graphs');
    const sel = $('nt-graph');
    if (!sel) return;
    sel.innerHTML = '<option value="">— auto create —</option>';
    (data.graphs || data || []).forEach(g => {
      const opt = document.createElement('option');
      opt.value = g.id; opt.textContent = g.id.slice(0, 8);
      sel.appendChild(opt);
    });
  } catch { /* ignore */ }
}

async function loadGraphs() {
  try {
    const data = await api.get('/task-graphs');
    (data.graphs || data || []).forEach(g => {
      const opt = document.createElement('option');
      opt.value = g.id; opt.textContent = g.id.slice(0, 8);
      document.getElementById('graph-select').appendChild(opt);
    });
  } catch { /* ignore */ }
}

async function loadTasks() {
  try {
    currentGraphId = document.getElementById('graph-select').value;
    const params = currentGraphId ? `?graph_id=${currentGraphId}` : '';
    const data = await api.get(`/tasks${params}`);
    if (board) board.setCards(data.tasks || data || []);
  } catch (e) {
    const c = document.getElementById('kanban-container');
    if (c) c.innerHTML = `<div class="card">Error: ${e.message}</div>`;
  }
}

async function showDetail(taskId) {
  try {
    const t = await api.get(`/tasks/${taskId}`);
    document.getElementById('task-detail').innerHTML = `
      <h3>${t.title||taskId}</h3>
      ${t.description ? `<p>${t.description}</p>` : ''}
      <p><strong>Status:</strong> <span class="badge badge-${(t.status||'').toLowerCase()}">${t.status}</span></p>
      <p><strong>Assigned:</strong> ${t.assigned_to||'—'}</p>
      <p><strong>Deps:</strong> ${(t.depends_on||[]).join(', ')||'none'}</p>
      ${t.error_message?`<p style="color:var(--danger)"><strong>Error:</strong> ${t.error_message}</p>`:''}
      <div class="actions"><button class="secondary" onclick="this.closest('.modal-overlay').classList.add('hidden')">Close</button></div>`;
    document.getElementById('task-modal').classList.remove('hidden');
  } catch(e){ alert(`Failed: ${e.message}`); }
}

async function onCreateTask(e) {
  e.preventDefault();
  const title = $('nt-title').value.trim();
  if (!title) return;
  const body = {
    title,
    description: $('nt-desc').value.trim(),
    assigned_to: $('nt-assign').value || null,
    graph_id: $('nt-graph').value || null,
    priority: $('nt-priority').value,
  };
  try {
    await api.post('/tasks', body);
    $('new-task-modal').classList.add('hidden');
    $('new-task-form').reset();
    loadGraphs();
    loadTasks();
  } catch (err) {
    alert(`Create task failed: ${err.message}`);
  }
}

async function onCreateGraph(e) {
  e.preventDefault();
  const body = {};
  const gid = $('ng-id').value.trim();
  const mid = $('ng-motion').value.trim();
  if (gid) body.id = gid;
  if (mid) body.motion_id = mid;
  try {
    await api.post('/task-graphs', body);
    $('new-graph-modal').classList.add('hidden');
    $('new-graph-form').reset();
    loadGraphs();
  } catch (err) {
    alert(`Create graph failed: ${err.message}`);
  }
}

function subscribeWS() {
  ws.subscribe(['tasks']);
  // Phase 13.2b: TASK_UPDATE canonical type (aliased from TASK_STATUS etc)
  unsubTask = ws.on('TASK_UPDATE', p => {
    if (board && p.task_id) board.moveCard(p.task_id, p.status);
  });
}

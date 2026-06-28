/* Reusable Task Board Component — columns by status.
Backend-agnostic: works with Agora's task model, not tied to
any specific agent framework (Hermes, OpenCode, etc). */
export class TaskBoard {
  constructor(container, opts = {}) {
    this.container = container;
    this.columns = opts.columns || ['PENDING', 'ASSIGNED', 'RUNNING', 'DONE', 'FAILED'];
    this.onCardClick = opts.onCardClick || (() => {});
    this.cards = {};
    this.init();
  }

  init() {
    this.container.innerHTML = `<div class="task-board"></div>`;
    this.board = this.container.querySelector('.task-board');
    this.columns.forEach(col => {
      const div = document.createElement('div');
      div.className = 'task-col';
      div.dataset.status = col;
      div.innerHTML = `<h4>${col} <span class="count">(0)</span></h4><div class="cards"></div>`;
      this.board.appendChild(div);
      this.cards[col] = div.querySelector('.cards');
    });
  }

  setCards(items) {
    this.columns.forEach(col => {
      const list = this.cards[col];
      const colItems = items.filter(i => (i.status || 'PENDING').toUpperCase() === col);
      list.innerHTML = colItems.map(item => this.renderCard(item)).join('');
      const count = list.closest('.task-col').querySelector('.count');
      if (count) count.textContent = `(${colItems.length})`;
    });
    this.bindClicks();
  }

  renderCard(item) {
    const deps = item.depends_on?.length ? `dep:${item.depends_on.length}` : '';
    const agent = item.assigned_to ? `→ ${item.assigned_to}` : '';
    const time = item.started_at ? this.fmtTime(item.started_at) : '';
    return `<div class="task-card" data-id="${item.id}">
      <div class="title">${this.escape(item.title || item.id)}</div>
      <div class="meta">${[deps, agent, time].filter(Boolean).join(' · ')}</div>
    </div>`;
  }

  escape(s) { return String(s).replace(/[<>&"']/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;',"'":'&#39;'}[c])); }

  fmtTime(ts) {
    const d = new Date(ts); const now = new Date();
    const sec = Math.floor((now - d) / 1000);
    if (sec < 60) return `${sec}s`;
    if (sec < 3600) return `${Math.floor(sec / 60)}m`;
    return `${Math.floor(sec / 3600)}h`;
  }

  bindClicks() {
    this.board.querySelectorAll('.task-card').forEach(card => {
      card.onclick = () => this.onCardClick(card.dataset.id);
    });
  }

  moveCard(taskId, newStatus) {
    const card = this.board.querySelector(`[data-id="${taskId}"]`);
    if (!card) return;
    const targetCol = this.cards[newStatus.toUpperCase()];
    if (!targetCol) return;
    targetCol.appendChild(card);
    this.updateCounts();
  }

  updateCounts() {
    this.columns.forEach(col => {
      const count = this.cards[col].children.length;
      const badge = this.board.querySelector(`[data-status="${col}"] .count`);
      if (badge) badge.textContent = `(${count})`;
    });
  }

  destroy() { this.container.innerHTML = ''; }
}

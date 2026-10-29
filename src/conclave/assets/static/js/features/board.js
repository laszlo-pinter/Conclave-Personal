// static/js/features/board.js — Board: Spalten, Karten, Ticketansicht, Live-Refresh (B5)
//
// Werte aus der API kommen nur per textContent ins DOM; Beschreibung und Kommentare
// laufen ueber renderMarkdown() (DOMPurify).

let _board = {statuses: [], projects: [], tasks: [], changes: null, open: null, query: ''};
let _boardTimer = null;
const BOARD_POLL_MS = 5000;

function _boardEl(tag, cls, text) {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  if (text !== undefined && text !== null) el.textContent = text;
  return el;
}

function _taskPath(ref) {
  const i = ref.lastIndexOf('#');
  return `/board/projects/${encodeURIComponent(ref.slice(0, i))}/tasks/${Number(ref.slice(i + 1))}`;
}

function _boardProject() { return document.getElementById('boardProject').value; }
function _boardShowDone() { return document.getElementById('boardShowDone').checked; }

function originLabel(origin) {
  if (origin === 'human') return t('board.originHuman');
  if (origin === 'agent') return t('board.originAgent');
  if (origin === 'system') return t('board.originSystem');
  return t('board.originUnknown');
}

function _boardDate(iso) {
  if (!iso) return '';
  return new Date(iso).toLocaleString(getLanguage() === 'en' ? 'en-US' : 'de-DE',
    {day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit'});
}

// ── Laden ────────────────────────────────────────────────────────────────

async function loadBoard() {
  try {
    await _reloadBoard();
  } catch (e) {
    _boardMessage(e.message, true);
  }
  _startBoardPolling();
}

// Uebersicht (Spalten, Projekte, Zaehler), Tickets und ein offenes Ticket neu laden
async function _reloadBoard() {
  const data = await req('GET', '/board');
  _board.statuses = data.statuses || [];
  _board.projects = data.projects || [];
  _board.changes = data.changes;
  _renderBoardProjects();
  await _loadBoardTasks();
  // Per Klick auf den Hintergrund geschlossen: nicht weiter nachladen
  if (!document.getElementById('overlayBoardTask').classList.contains('open')) _board.open = null;
  if (_board.open) await _renderOpenTask();
}

async function _loadBoardTasks() {
  const params = new URLSearchParams();
  const project = _boardProject();
  if (project) params.set('project', project);
  params.set('include_done', _boardShowDone() ? 'true' : 'false');
  let data;
  if (_board.query) {
    params.set('q', _board.query);
    data = await req('GET', '/board/search?' + params);
  } else {
    data = await req('GET', '/board/tasks?' + params);
  }
  _board.tasks = data.tasks || [];
  renderBoard();
}

function _boardMessage(text, isError) {
  const cols = document.getElementById('boardColumns');
  cols.replaceChildren(_boardEl('div', 'surface-empty' + (isError ? ' board-error' : ''), text));
}

function _renderBoardProjects() {
  const sel = document.getElementById('boardProject');
  const current = sel.value;
  const all = _boardEl('option', '', t('board.allProjects'));
  all.value = '';
  const options = [all, ..._board.projects.map(p => {
    const o = _boardEl('option', '', `${p.name} (${p.slug})`);
    o.value = p.slug;
    return o;
  })];
  sel.replaceChildren(...options);
  sel.value = _board.projects.some(p => p.slug === current) ? current : '';
  const newSel = document.getElementById('boardNewProject');
  newSel.replaceChildren(..._board.projects.map(p => {
    const o = _boardEl('option', '', `${p.name} (${p.slug})`);
    o.value = p.slug;
    return o;
  }));
}

// ── Spalten und Karten ───────────────────────────────────────────────────

function renderBoard() {
  const cols = document.getElementById('boardColumns');
  if (!_board.projects.length) { _boardMessage(t('board.noProjects')); return; }
  const done = _board.statuses[_board.statuses.length - 1];
  cols.replaceChildren(..._board.statuses.map(status => {
    const col = _boardEl('div', 'board-col');
    col.dataset.status = status;
    const tasks = _board.tasks.filter(task => task.status === status);
    const head = _boardEl('div', 'board-col-head');
    head.append(_boardEl('span', 'board-col-name', status), _boardEl('span', 'board-col-count', String(tasks.length)));
    const list = _boardEl('div', 'board-col-list');
    tasks.forEach(task => list.appendChild(_boardCard(task)));
    if (status === done && !_boardShowDone() && !_board.query) {
      list.appendChild(_boardEl('div', 'surface-empty', t('board.doneHidden')));
    }
    col.append(head, list);
    _bindColumnDrop(col);
    return col;
  }));
}

function _boardCard(task) {
  const card = _boardEl('div', 'board-card' + (task.human ? ' human' : ''));
  card.draggable = true;
  card.dataset.action = 'board-open-task';
  card.dataset.ref = task.ref;
  card.dataset.project = task.project;
  const top = _boardEl('div', 'board-card-top');
  top.appendChild(_boardEl('span', 'board-ref', task.ref));
  if (task.human) {
    const mark = _boardEl('span', 'board-human', t('board.humanShort'));
    mark.title = t('board.humanOnly');
    top.appendChild(mark);
  }
  card.append(top, _boardEl('div', 'board-card-title', task.title));
  if (task.tags.length) {
    const tags = _boardEl('div', 'board-tags');
    task.tags.forEach(tag => tags.appendChild(_boardEl('span', 'board-tag', tag)));
    card.appendChild(tags);
  }
  card.addEventListener('dragstart', e => {
    e.dataTransfer.setData('text/plain', task.ref);
    e.dataTransfer.effectAllowed = 'move';
    card.classList.add('dragging');
  });
  card.addEventListener('dragend', () => card.classList.remove('dragging'));
  return card;
}

function _bindColumnDrop(col) {
  col.addEventListener('dragover', e => { e.preventDefault(); col.classList.add('drop'); });
  col.addEventListener('dragleave', e => { if (!col.contains(e.relatedTarget)) col.classList.remove('drop'); });
  col.addEventListener('drop', e => {
    e.preventDefault();
    col.classList.remove('drop');
    const ref = e.dataTransfer.getData('text/plain');
    const task = _board.tasks.find(x => x.ref === ref);
    if (!task) return;
    // Index unter den Karten desselben Projekts in der Zielspalte, ohne die Karte selbst
    const others = [...col.querySelectorAll('.board-card')]
      .filter(c => c.dataset.project === task.project && c.dataset.ref !== ref);
    const index = others.filter(c => { const r = c.getBoundingClientRect(); return r.top + r.height / 2 < e.clientY; }).length;
    moveBoardTask(task, col.dataset.status, index);
  });
}

async function moveBoardTask(task, status, index) {
  const body = {index};
  if (status !== task.status) body.status = status;
  try {
    await req('PATCH', _taskPath(task.ref), body);
  } catch (e) {
    toast(e.message, 'err');
  }
  await _refreshBoard();
}

// ── Suche ────────────────────────────────────────────────────────────────

let _boardSearchTimer = null;
function onBoardSearch() {
  clearTimeout(_boardSearchTimer);
  _boardSearchTimer = setTimeout(() => {
    _board.query = document.getElementById('boardSearch').value.trim();
    _loadBoardTasks().catch(e => _boardMessage(e.message, true));
  }, 250);
}

function onBoardFilter() {
  _loadBoardTasks().catch(e => _boardMessage(e.message, true));
}

// ── Ticketansicht ────────────────────────────────────────────────────────

async function openBoardTask(ref) {
  _board.open = ref;
  document.getElementById('boardCommentBody').value = '';
  // Nichts vom zuvor geoeffneten Ticket stehen lassen
  document.getElementById('boardTaskRef').textContent = ref;
  ['boardTaskTitle', 'boardTaskTags', 'boardTaskComments', 'boardTaskHistory']
    .forEach(id => document.getElementById(id).replaceChildren());
  document.getElementById('boardTaskDesc').replaceChildren(_boardEl('div', 'surface-empty', t('common.loading')));
  openOverlay('overlayBoardTask');
  await _renderOpenTask();
}

function closeBoardTask() {
  _board.open = null;
  closeOverlay('overlayBoardTask');
}

async function _renderOpenTask() {
  const ref = _board.open;
  if (!ref) return;
  let task, history;
  try {
    [task, {history}] = await Promise.all([req('GET', _taskPath(ref)), req('GET', _taskPath(ref) + '/history')]);
  } catch (e) {
    document.getElementById('boardTaskDesc').replaceChildren(_boardEl('div', 'board-error', e.message));
    return;
  }
  if (_board.open !== ref) return;
  document.getElementById('boardTaskRef').textContent = task.ref;
  document.getElementById('boardTaskTitle').textContent = task.title;
  const status = document.getElementById('boardTaskStatus');
  status.replaceChildren(..._board.statuses.map(s => { const o = _boardEl('option', '', s); o.value = s; return o; }));
  status.value = task.status;
  document.getElementById('boardTaskHuman').checked = task.human;
  const tags = document.getElementById('boardTaskTags');
  tags.replaceChildren(...task.tags.map(tag => _boardEl('span', 'board-tag', tag)));

  const desc = document.getElementById('boardTaskDesc');
  if (task.description) {
    // safe-html: renderMarkdown() filtert ueber DOMPurify, ohne DOMPurify nur esc()
    desc.innerHTML = renderMarkdown(task.description);
  } else {
    desc.replaceChildren(_boardEl('div', 'surface-empty', t('board.noDescription')));
  }

  const comments = document.getElementById('boardTaskComments');
  comments.replaceChildren(...(task.comments.length ? task.comments.map(_boardComment)
    : [_boardEl('div', 'surface-empty', t('board.noComments'))]));

  const hist = document.getElementById('boardTaskHistory');
  hist.replaceChildren(...(history.length ? history.map(_boardEvent)
    : [_boardEl('div', 'surface-empty', t('board.noHistory'))]));
}

function _boardComment(c) {
  const item = _boardEl('div', 'board-comment');
  item.dataset.origin = c.origin || 'unknown';
  const head = _boardEl('div', 'board-comment-head');
  head.appendChild(_boardEl('span', 'board-origin origin-' + (c.origin || 'unknown'), originLabel(c.origin)));
  if (c.author_name) head.appendChild(_boardEl('span', 'board-author', c.author_name));
  head.appendChild(_boardEl('span', 'board-time', _boardDate(c.created_at)));
  const body = _boardEl('div', 'board-comment-body msg-content');
  // safe-html: renderMarkdown() filtert ueber DOMPurify, ohne DOMPurify nur esc()
  body.innerHTML = renderMarkdown(c.body);
  item.append(head, body);
  return item;
}

function _boardEvent(ev) {
  const item = _boardEl('div', 'board-event');
  item.append(_boardEl('span', 'board-time', _boardDate(ev.created_at)),
              _boardEl('span', 'board-origin origin-' + (ev.origin || 'unknown'), originLabel(ev.origin)),
              _boardEl('span', 'board-event-field', t('board.field.' + ev.field)));
  if (ev.field === 'description') {
    // Volltext nur aufklappbar, damit der Verlauf lesbar bleibt
    const details = _boardEl('details', 'board-event-details');
    details.append(_boardEl('summary', '', t('board.showChange')),
                   _boardEl('pre', '', ev.old || ''), _boardEl('pre', '', ev.new || ''));
    item.appendChild(details);
  } else {
    item.appendChild(_boardEl('span', 'board-event-change', `${ev.old ?? '-'} → ${ev.new ?? '-'}`));
  }
  return item;
}

async function saveBoardTaskField(field) {
  const ref = _board.open;
  if (!ref) return;
  const value = field === 'status' ? document.getElementById('boardTaskStatus').value
                                   : document.getElementById('boardTaskHuman').checked;
  try {
    await req('PATCH', _taskPath(ref), {[field]: value});
  } catch (e) {
    toast(e.message, 'err');
  }
  await _refreshBoard();
}

async function addBoardComment() {
  const ref = _board.open;
  const input = document.getElementById('boardCommentBody');
  const body = input.value.trim();
  if (!ref || !body) return;
  try {
    await req('POST', _taskPath(ref) + '/comments', {body});
    input.value = '';
  } catch (e) {
    toast(e.message, 'err');
    return;
  }
  await _refreshBoard();
}

// ── Neues Ticket ─────────────────────────────────────────────────────────

function openBoardNew() {
  if (!_board.projects.length) { toast(t('board.noProjects'), 'err'); return; }
  ['boardNewTitle', 'boardNewDesc', 'boardNewTags'].forEach(id => { document.getElementById(id).value = ''; });
  document.getElementById('boardNewHuman').checked = false;
  const project = _boardProject();
  if (project) document.getElementById('boardNewProject').value = project;
  openOverlay('overlayBoardNew');
  document.getElementById('boardNewTitle').focus();
}

async function createBoardTask() {
  const title = document.getElementById('boardNewTitle').value.trim();
  if (!title) { toast(t('board.titleRequired'), 'err'); return; }
  const tags = document.getElementById('boardNewTags').value.split(',').map(s => s.trim()).filter(Boolean);
  try {
    await req('POST', '/board/tasks', {
      project: document.getElementById('boardNewProject').value, title,
      description: document.getElementById('boardNewDesc').value, tags,
      human: document.getElementById('boardNewHuman').checked,
    });
  } catch (e) {
    toast(e.message, 'err');
    return;
  }
  closeOverlay('overlayBoardNew');
  await _refreshBoard();
}

// ── Live-Refresh ─────────────────────────────────────────────────────────

async function _refreshBoard() {
  try {
    await _reloadBoard();
  } catch (e) {
    toast(e.message, 'err');
  }
}

function _boardActive() {
  return document.querySelector('.sb-tab.active')?.dataset.tab === 'board';
}

function _startBoardPolling() {
  if (_boardTimer) return;
  _boardTimer = setInterval(async () => {
    if (!_boardActive()) { clearInterval(_boardTimer); _boardTimer = null; return; }
    if (document.visibilityState === 'hidden') return;
    try {
      const {changes} = await req('GET', '/board/changes');
      if (changes !== _board.changes) await _reloadBoard();
    } catch { /* naechster Versuch */ }
  }, BOARD_POLL_MS);
}

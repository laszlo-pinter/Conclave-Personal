// static/js/features/board.js — Board: Spalten, Karten, Ticketansicht, Live-Refresh (B5)
//
// Werte aus der API kommen nur per textContent ins DOM; Beschreibung und Kommentare
// laufen ueber renderMarkdown() (DOMPurify).

let _board = {statuses: [], projects: [], tasks: [], changes: null, open: null, query: '',
              control: {pauses: [], hints: []}, role: '', approvalsOnly: false, stuck: ''};
let _boardTimer = null;
// Versionierte Board-API (T3); /board ohne Version ist ein abgekuendigter Alias
const BOARD_API = '/board/v1';
const BOARD_POLL_MS = 5000;
const REVIEW_STUCK_MS = 30 * 60 * 1000;     // "laeuft" laenger als 30 Minuten: haengt (P4)
const REVIEW_RED_LIMIT = 3;                 // E-R3: nach drei roten uebernimmt der Mensch

function _boardEl(tag, cls, text) {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  if (text !== undefined && text !== null) el.textContent = text;
  return el;
}

function _taskPath(ref) {
  const i = ref.lastIndexOf('#');
  return `${BOARD_API}/projects/${encodeURIComponent(ref.slice(0, i))}/tasks/${Number(ref.slice(i + 1))}`;
}

function _boardProject() { return document.getElementById('boardProject').value; }
function _boardShowDone() { return document.getElementById('boardShowDone').checked; }

function originLabel(origin) {
  if (origin === 'human') return t('board.originHuman');
  if (origin === 'agent') return t('board.originAgent');
  if (origin === 'reviewer') return t('board.originReviewer');
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
    // Drag & Drop und der Hinweis auf Freigaben nur fuer den Menschen (P4, Rolle wie in R5)
    _board.role = await whoami();
    await _reloadBoard();
  } catch (e) {
    _boardMessage(e.message, true);
  }
  _startBoardPolling();
}

// Uebersicht (Spalten, Projekte, Zaehler), Tickets und ein offenes Ticket neu laden
async function _reloadBoard() {
  const data = await req('GET', BOARD_API);
  _board.statuses = data.statuses || [];
  _board.projects = data.projects || [];
  _board.changes = data.changes;
  _board.control = data.control || {pauses: [], hints: []};
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
    data = await req('GET', BOARD_API + '/search?' + params);
  } else {
    data = await req('GET', BOARD_API + '/tasks?' + params);
  }
  _board.tasks = data.tasks || [];
  renderBoard();
  renderBoardControl();
  renderBoardApprovals();
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

// Welche Tickets gerade als "haengt" gelten: aendert sich mit der Uhr, nicht mit dem Board (P4, Review-B1)
function _stuckKey() {
  return _board.tasks.filter(task => _reviewState(task) === 'stuck').map(task => task.ref).join(' ');
}

function renderBoard() {
  _board.stuck = _stuckKey();
  const cols = document.getElementById('boardColumns');
  if (!_board.projects.length) { _boardMessage(t('board.noProjects')); return; }
  const done = _board.statuses[_board.statuses.length - 1];
  cols.replaceChildren(..._board.statuses.map(status => {
    const col = _boardEl('div', 'board-col');
    col.dataset.status = status;
    // Steuertickets stehen im Banner ueber den Spalten, nicht als Karte (P6)
    const tasks = _board.tasks.filter(task => task.status === status && task.kind !== 'control'
                                              && (!_board.approvalsOnly || _waitsForApproval(task)));
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

// ── Review-Status (P4) ──────────────────────────────────────────────────

function _reviewState(task) {
  const review = task.review || {};
  const state = review.state || 'none';
  if (state === 'running' && review.at && Date.now() - Date.parse(review.at) > REVIEW_STUCK_MS) return 'stuck';
  return state;
}

function _waitsForApproval(task) {
  return task.status === 'review' && _reviewState(task) === 'passed';
}

const REVIEW_SYMBOLS = {running: '●', stuck: '⚠', passed: '✓', rework: '↻', failed: '✕'};

// Badge mit Symbol und Text, nie nur Farbe; long = Ticketansicht mit den Zahlen
function _reviewBadge(task, long) {
  const state = _reviewState(task);
  if (state === 'none') return null;
  const review = task.review || {};
  let text = t('board.review.' + state);
  const firstColumn = task.status === _board.statuses[0];
  if ((state === 'rework' || state === 'failed') && firstColumn && review.at) {
    text += ' · ' + t('board.review.fromReview', {date: _boardDate(review.at)});
  }
  if (state === 'failed' && review.red_count) {
    text += ' · ' + t('board.review.redRounds', {n: review.red_count, max: REVIEW_RED_LIMIT});
  }
  if (long && (state === 'rework' || state === 'failed' || state === 'passed')
      && review.blocking !== null && review.blocking !== undefined) {
    text += ' · ' + t('board.review.counts', {blocking: review.blocking, suggestions: review.suggestions || 0});
  }
  const badge = _boardEl('span', 'board-review');
  badge.dataset.state = state;
  badge.setAttribute('aria-label', t('board.review.label') + ': ' + text);
  badge.title = text;
  const symbol = _boardEl('span', 'board-review-symbol' + (state === 'running' ? ' pulse' : ''), REVIEW_SYMBOLS[state]);
  symbol.setAttribute('aria-hidden', 'true');
  badge.append(symbol, _boardEl('span', 'board-review-text', text));
  return badge;
}

function renderBoardApprovals() {
  const hint = document.getElementById('boardApprovals');
  if (!hint) return;
  const count = _board.tasks.filter(_waitsForApproval).length;
  hint.hidden = _board.role !== 'human' || (!count && !_board.approvalsOnly);
  hint.textContent = t(count === 1 ? 'board.approvals.one' : 'board.approvals.many', {n: count});
  hint.setAttribute('aria-pressed', _board.approvalsOnly ? 'true' : 'false');
  hint.classList.toggle('active', _board.approvalsOnly);
}

function toggleBoardApprovals() {
  _board.approvalsOnly = !_board.approvalsOnly;
  renderBoard();
  renderBoardApprovals();
}

function _boardCard(task) {
  const card = _boardEl('div', 'board-card' + (task.human ? ' human' : ''));
  // Verschieben aendert Spalte und Prioritaet: nur der Mensch (P1, P4)
  card.draggable = _board.role === 'human';
  card.dataset.action = 'board-open-task';
  card.dataset.ref = task.ref;
  card.dataset.project = task.project;
  const top = _boardEl('div', 'board-card-top');
  top.appendChild(_boardEl('span', 'board-ref', task.ref));
  if (task.initiative_ref) {                    // Vorhaben-Nummer (P2), z. B. conclave/sich-3
    top.appendChild(_boardEl('span', 'board-initiative', task.initiative_ref));
  }
  if (task.human) {
    const mark = _boardEl('span', 'board-human', t('board.humanShort'));
    mark.title = t('board.humanOnly');
    top.appendChild(mark);
  }
  card.append(top, _boardEl('div', 'board-card-title', task.title));
  const badge = _reviewBadge(task, false);
  if (badge) card.appendChild(badge);
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
    if (_board.role !== 'human') return;
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
  ['boardTaskTitle', 'boardTaskReview', 'boardTaskTags', 'boardTaskComments', 'boardTaskHistory']
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
  const review = _reviewBadge(task, true);
  document.getElementById('boardTaskReview').replaceChildren(...(review ? [review] : []));
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
  if (ev.field === 'description' || ev.field === 'comment') {
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
    await req('POST', BOARD_API + '/tasks', {
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

// ── Steuertickets: Banner und Pause (P6) ─────────────────────────────────

// Offene Pausen und Hinweise aus /board (gilt unabhaengig von Filter und Suche), dazu
// quittierte Hinweise aus der Ticketliste, bis der Mensch sie schliesst.
function _boardControlEntries() {
  const done = _board.statuses[_board.statuses.length - 1];
  const entries = [..._board.control.pauses, ..._board.control.hints].map(c => ({...c, ack_by: null}));
  _board.tasks.filter(task => task.kind === 'control' && task.status !== done && task.directive?.ack_by)
    .forEach(task => {
      if (!entries.some(e => e.task === task.ref)) {
        entries.push({task: task.ref, type: task.directive.type, reason: task.title, text: task.description,
                      scope: task.directive.scope === 'all' ? 'all' : task.project, ack_by: task.directive.ack_by});
      }
    });
  return entries;
}

function renderBoardControl() {
  const box = document.getElementById('boardControl');
  const entries = _boardControlEntries();
  box.hidden = !entries.length;
  box.classList.toggle('paused', entries.some(e => e.type === 'pause'));
  if (!entries.length) { box.replaceChildren(); return; }
  box.replaceChildren(_boardEl('div', 'board-control-head', t('board.controlTitle')), ...entries.map(e => {
    const item = _boardEl('div', 'board-control-item ' + (e.type === 'pause' ? 'pause' : 'hint'));
    item.dataset.ref = e.task;
    const kind = _boardEl('span', 'board-control-kind', t(e.type === 'pause' ? 'board.controlPause' : 'board.controlHint'));
    const scope = _boardEl('span', 'board-control-scope',
      e.scope === 'all' ? t('board.controlAll') : `${t('board.project')}: ${e.scope}`);
    const body = _boardEl('div', 'board-control-body');
    body.appendChild(_boardEl('div', 'board-control-reason', e.reason));
    if (e.text) body.appendChild(_boardEl('div', 'board-control-text', e.text));
    if (e.type === 'hint') {
      body.appendChild(_boardEl('div', 'board-control-ack',
        e.ack_by ? t('board.controlAcked').replace('{name}', e.ack_by) : t('board.controlOpen')));
    }
    const close = _boardEl('button', 'btn-sm board-control-close', t('board.controlClose'));
    close.dataset.action = 'board-close-control';
    close.dataset.ref = e.task;
    item.append(kind, _boardEl('span', 'board-ref', e.task), scope, body, close);
    return item;
  }));
}

async function pauseBoardAgents() {
  const slug = _boardProject() || _board.projects[0]?.slug;
  if (!slug) { toast(t('board.noProjects'), 'err'); return; }
  try {
    await req('POST', BOARD_API + '/tasks', {project: slug, title: t('board.pauseTitle'), kind: 'control',
                                       control: 'pause', scope: 'all'});
    toast(t('board.paused'), 'ok');
  } catch (e) {
    toast(e.message, 'err');
  }
  await _refreshBoard();
}

async function closeBoardControl(ref) {
  const done = _board.statuses[_board.statuses.length - 1];
  try {
    await req('PATCH', _taskPath(ref), {status: done});
  } catch (e) {
    toast(e.message, 'err');
  }
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
      const {changes} = await req('GET', BOARD_API + '/changes');
      if (changes !== _board.changes) await _reloadBoard();
      else if (_stuckKey() !== _board.stuck) {
        // Ein Review ueberschreitet die 30 Minuten, ohne dass sich etwas aendert: neu zeichnen
        renderBoard();
        renderBoardApprovals();
        if (_board.open) await _renderOpenTask();
      }
    } catch { /* naechster Versuch */ }
  }, BOARD_POLL_MS);
}

// ── Desktop-Hinweis bei Review-Ergebnissen (P8) ──────────────────────────
//
// Abschaltbar (Standard aus); die Erlaubnis fragt erst ein Klick an. Gemeldet wird nur, wenn das
// Fenster nicht im Vordergrund ist, und jedes Ergebnis nur einmal, auch nach dem Neuladen: Der
// Zeitpunkt des zuletzt gesehenen Ergebnisses steht in localStorage.

const NOTIFY_KEY = 'conclave.board.notify';
const NOTIFY_SEEN_KEY = 'conclave.board.notifySeen';
const NOTIFY_POLL_MS = 15000;
const NOTIFY_STATES = ['passed', 'rework', 'failed'];
let _notify = {timer: null, changes: null};

function _store(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, value);
  } catch { /* privates Fenster: dann eben ohne Merken */ }
  return null;
}

function _notifySupported() { return typeof Notification !== 'undefined'; }

function boardNotifyEnabled() {
  return _notifySupported() && Notification.permission === 'granted' && _store(NOTIFY_KEY) === '1';
}

function renderBoardNotify() {
  const btn = document.getElementById('boardNotify');
  if (!btn) return;
  btn.hidden = !_notifySupported();
  const on = boardNotifyEnabled();
  btn.setAttribute('aria-pressed', on ? 'true' : 'false');
  btn.textContent = t(on ? 'board.notifyOn' : 'board.notifyOff');
}

async function toggleBoardNotify() {
  if (!_notifySupported()) return;
  if (boardNotifyEnabled()) {
    _store(NOTIFY_KEY, '0');
  } else {
    const permission = Notification.permission === 'granted' ? 'granted' : await Notification.requestPermission();
    if (permission !== 'granted') {
      toast(t('board.notifyDenied'), 'err');
    } else {
      // Nur Ergebnisse ab jetzt: der neueste Review-Zeitpunkt des Servers (nicht die Uhr dieses Rechners)
      try {
        const data = await req('GET', BOARD_API + '/tasks?include_done=true');
        _store(NOTIFY_SEEN_KEY, (data.tasks || []).map(task => (task.review || {}).at || '').sort().pop() || '');
      } catch (e) {
        toast(e.message, 'err');
        return;
      }
      _store(NOTIFY_KEY, '1');
      _notify.changes = null;
    }
  }
  renderBoardNotify();
}

function boardNotifyText(task) {
  const review = task.review || {};
  const verdict = t('board.notify.' + review.state);
  let body = verdict;
  if (review.state === 'passed') body += ' – ' + t('board.notify.waiting');
  else if (review.blocking !== null && review.blocking !== undefined) {
    body += ' – ' + t('board.review.counts', {blocking: review.blocking, suggestions: review.suggestions || 0});
  }
  return {title: `${task.ref} ${task.title}`, body};
}

async function checkBoardNotifications() {
  if (!boardNotifyEnabled()) return;
  const {changes} = await req('GET', BOARD_API + '/changes');
  if (changes === _notify.changes) return;
  _notify.changes = changes;
  const seen = _store(NOTIFY_SEEN_KEY) || '';
  const data = await req('GET', BOARD_API + '/tasks?include_done=true');
  const fresh = (data.tasks || []).filter(task => NOTIFY_STATES.includes((task.review || {}).state)
                                            && (task.review.at || '') > seen);
  if (!fresh.length) return;
  _store(NOTIFY_SEEN_KEY, fresh.map(task => task.review.at).sort().pop());
  if (document.visibilityState === 'visible' && document.hasFocus()) return;   // sieht es ohnehin
  for (const task of fresh) {
    const {title, body} = boardNotifyText(task);
    const note = new Notification(title, {body, tag: 'conclave-review-' + task.ref});
    note.onclick = () => {
      window.focus();
      switchTab('board');
      openBoardTask(task.ref);
      note.close();
    };
  }
}

function startBoardNotifications() {
  renderBoardNotify();
  if (_notify.timer) return;
  _notify.timer = setInterval(() => { checkBoardNotifications().catch(() => { /* naechster Versuch */ }); },
                              NOTIFY_POLL_MS);
}

// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Laszlo Pinter
//
// board-page.js — Grundlage der eigenstaendigen Board-Seite (board.html, U1): Texte, API-Aufruf
// mit Token, Anmeldung, Theme, Meldungen und die Bedienung per data-action. Die Board-Ansicht
// selbst steht in board.js, genau wie im Studio von Conclave Personal.
//
// Das Token liegt nur im sessionStorage dieses Tabs (wie im Studio seit v0.7.0). Ein Token aus dem
// Link (#token=…, von `conclave desktop`) gilt erst nach der Pruefung seiner Rolle.

const BOARD_PAGE_LANGS = ['de', 'en'];
const BOARD_PAGE_THEMES = ['system', 'light', 'dark'];
// Dieselben Schluessel wie im Studio: gleiche Sprache, gleiches Theme, gleiches Token je Tab
const BOARD_TOKEN_KEY = 'conclave_api_key';
const BOARD_LANG_KEY = 'conclave_ui_lang';
const BOARD_THEME_KEY = 'conclave_ui_theme';

function _pageGet(storage, key) {
  try { return storage.getItem(key) || ''; } catch { return ''; }
}

function _pageSet(storage, key, value) {
  try {
    if (value) storage.setItem(key, value);
    else storage.removeItem(key);
  } catch { /* nur fuer diese Sitzung */ }
}

// ── Texte ────────────────────────────────────────────────────────────────

function getLanguage() {
  const saved = _pageGet(localStorage, BOARD_LANG_KEY);
  return BOARD_PAGE_LANGS.includes(saved) ? saved : 'de';
}

function t(key, vars = {}) {
  let text = BOARD_I18N[getLanguage()][key] || BOARD_I18N.de[key] || key;
  Object.entries(vars).forEach(([name, value]) => { text = text.replaceAll(`{${name}}`, String(value)); });
  return text;
}

function applyBoardTranslations() {
  document.documentElement.lang = getLanguage();
  document.title = t('board.page.title');
  document.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = t(el.dataset.i18n); });
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    el.setAttribute('placeholder', t(el.dataset.i18nPlaceholder));
  });
  document.querySelectorAll('[data-i18n-title]').forEach(el => { el.setAttribute('title', t(el.dataset.i18nTitle)); });
  const lang = document.getElementById('boardPageLang');
  if (lang) lang.value = getLanguage();
}

// ── Theme ────────────────────────────────────────────────────────────────

function _boardTheme() {
  const saved = _pageGet(localStorage, BOARD_THEME_KEY);
  return BOARD_PAGE_THEMES.includes(saved) ? saved : 'system';
}

function applyBoardTheme() {
  const theme = _boardTheme();
  if (theme === 'system') delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme;
  const select = document.getElementById('boardPageTheme');
  if (select) select.value = theme;
}

// ── Meldungen und Dialoge ────────────────────────────────────────────────

function toast(msg, type = 'ok') {
  const box = document.getElementById('toasts');
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  box.appendChild(el);
  setTimeout(() => el.remove(), type === 'err' ? 10000 : 3200);
}

function openOverlay(id) { document.getElementById(id).classList.add('open'); }
function closeOverlay(id) { document.getElementById(id).classList.remove('open'); }

// ── API ──────────────────────────────────────────────────────────────────

let _boardToken = _pageGet(sessionStorage, BOARD_TOKEN_KEY);

function _authHeaders(token = _boardToken) {
  const headers = {'Content-Type': 'application/json'};
  if (token) headers.Authorization = 'Bearer ' + token;
  return headers;
}

async function req(method, path, body) {
  const opts = {method, headers: _authHeaders()};
  if (body !== undefined) opts.body = JSON.stringify(body);
  let res;
  try {
    res = await fetch(window.location.origin + path, opts);
  } catch (e) {
    throw new Error(t('board.page.serverUnreachable', {message: e.message}));
  }
  if (res.status === 401) openBoardLogin();
  if (res.status === 204) return null;
  const text = await res.text();
  if (!text) return null;
  let data;
  try { data = JSON.parse(text); } catch { throw new Error(t('board.page.serverError', {status: res.status})); }
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

// Rolle eines Tokens: 'human'/'agent'/…, '' = ungueltig (401/403), null = nicht pruefbar
async function _roleOf(token) {
  try {
    const res = await fetch(window.location.origin + '/auth/whoami', {headers: _authHeaders(token)});
    if (res.ok) return (await res.json()).role || '';
    return res.status === 401 || res.status === 403 ? '' : null;
  } catch { return null; }
}

async function whoami() {
  return (await _roleOf(_boardToken)) || '';
}

// ── Anmeldung ────────────────────────────────────────────────────────────

function _roleLabel(role) {
  if (role === 'human') return t('board.page.roleHuman');
  if (role === 'agent') return t('board.page.roleAgent');
  return role === null ? t('board.page.roleUnknown') : t('board.page.roleInvalid');
}

function _setBoardToken(token) {
  _boardToken = token;
  _pageSet(sessionStorage, BOARD_TOKEN_KEY, token);
  renderBoardLogin();
}

function renderBoardLogin() {
  const btn = document.getElementById('boardPageLogin');
  if (btn) btn.textContent = _boardToken ? t('board.page.logout') : t('board.page.login');
}

function openBoardLogin() {
  const input = document.getElementById('boardLoginToken');
  if (!input || document.getElementById('overlayBoardLogin').classList.contains('open')) return;
  input.value = '';
  openOverlay('overlayBoardLogin');
  input.focus();
}

async function submitBoardLogin() {
  const token = document.getElementById('boardLoginToken').value.trim();
  if (!token) return;
  const role = await _roleOf(token);
  if (!role) { toast(t('board.page.loginInvalid'), 'err'); return; }
  _setBoardToken(token);
  closeOverlay('overlayBoardLogin');
  await loadBoard();
}

function toggleBoardLogin() {
  if (!_boardToken) { openBoardLogin(); return; }
  _setBoardToken('');
  loadBoard();
}

// Token aus dem Link: in einem Tab ohne Token gilt ein Mensch-Token sofort (Start ueber
// conclave desktop), sonst fragt die Seite nach. Die Adresszeile wird sofort bereinigt.
async function _takeTokenFromLink() {
  const token = new URLSearchParams(window.location.hash.slice(1)).get('token');
  if (!token) return;
  history.replaceState(null, '', window.location.pathname + window.location.search);
  if (token === _boardToken) return;
  const role = await _roleOf(token);
  const silent = !_boardToken && role === 'human';
  if (!silent && !window.confirm(t('board.page.switchToken', {role: _roleLabel(role)}))) return;
  _setBoardToken(token);
}

// ── Start ────────────────────────────────────────────────────────────────

async function initBoardPage() {
  applyBoardTheme();
  applyBoardTranslations();
  if (typeof marked !== 'undefined') marked.setOptions({gfm: true, breaks: true, headerIds: false, mangle: false});
  const actions = {                     // board.js ist erst jetzt geladen
    ...BOARD_ACTIONS,
    'close-overlay':      (el) => closeOverlay(el.dataset.overlay),
    'board-login':        () => toggleBoardLogin(),
    'board-login-submit': () => submitBoardLogin(),
  };
  document.addEventListener('click', (e) => {
    const el = e.target.closest('[data-action]');
    const handler = el && actions[el.dataset.action];
    if (handler) handler(el);
  });
  document.querySelectorAll('.overlay').forEach(o => o.addEventListener('click', e => {
    if (e.target === o) o.classList.remove('open');
  }));
  bindBoardEvents();
  document.getElementById('boardPageLang').addEventListener('change', (e) => {
    _pageSet(localStorage, BOARD_LANG_KEY, e.target.value);
    applyBoardTranslations();
    renderBoardLogin();
    renderBoardNotify();
    loadBoard();
  });
  document.getElementById('boardPageTheme').addEventListener('change', (e) => {
    _pageSet(localStorage, BOARD_THEME_KEY, BOARD_PAGE_THEMES.includes(e.target.value) ? e.target.value : '');
    applyBoardTheme();
  });
  document.getElementById('boardLoginToken').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); submitBoardLogin(); }
  });
  await _takeTokenFromLink();
  renderBoardLogin();
  await loadBoard();                    // ohne gueltiges Token: Hinweis im Board und Anmeldedialog
  startBoardNotifications();
}

applyBoardTheme();                      // so frueh wie moeglich: kein Aufblitzen des falschen Modus
document.addEventListener('DOMContentLoaded', initBoardPage);

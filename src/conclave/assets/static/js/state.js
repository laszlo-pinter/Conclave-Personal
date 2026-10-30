// static/js/state.js — Zentraler State mit pub/sub
// Ersetzt die globalen let-Variablen durch ein reaktives State-Objekt.

// Token und API-Adresse liegen nur im sessionStorage dieses Tabs (R5): kein dauerhaftes
// Token im Browser; `conclave desktop` und `conclave web` liefern es beim Start neu.
const TOKEN_KEY = 'conclave_api_key'
const API_URL_KEY = 'conclave_api_url'

function storedValue(key) {
  try { return sessionStorage.getItem(key) || '' } catch { return '' }
}

function storeValue(key, value) {
  try {
    if (value) sessionStorage.setItem(key, value)
    else sessionStorage.removeItem(key)
  } catch {}
}

// Bis v0.6.1 lag das Token dauerhaft im localStorage: einmal in diesen Tab uebernehmen, dann loeschen.
function _moveLegacyToken() {
  try {
    for (const key of [TOKEN_KEY, API_URL_KEY]) {
      const old = localStorage.getItem(key)
      if (old && !storedValue(key)) storeValue(key, old)
      localStorage.removeItem(key)
    }
  } catch {}
}
_moveLegacyToken()

// Token aus dem URL-Fragment (#token=…, von `conclave desktop`/`conclave web`).
// Fragmente landen nicht in Server-Logs; die Adresszeile wird sofort bereinigt.
// Ein neues Token wird nie ungeprueft uebernommen: Es wartet als pendingToken, bis
// confirmPendingToken (auth.js) seine Rolle kennt. Ein Mensch-Token in einem leeren Tab
// (Start ueber conclave desktop/web) gilt sofort, sonst kommt eine Rueckfrage.
function _takeTokenFromFragment() {
  const token = new URLSearchParams(window.location.hash.slice(1)).get('token')
  if (!token) return {token: '', pending: ''}
  history.replaceState(null, '', window.location.pathname + window.location.search)
  if (storedValue(TOKEN_KEY) === token) return {token, pending: ''}
  return {token: '', pending: token}
}
const _fragment = _takeTokenFromFragment()

const _state = {
  api: (!_fragment.token && storedValue(API_URL_KEY)) || window.location.origin,
  apiKey: _fragment.token || storedValue(TOKEN_KEY) || '',
  pendingToken: _fragment.pending,
  currentConvId: null,
  currentMessages: [],
  conversations: [],
  participants: [],
  agents: [],
  presetsData: [],
  currentFloor: null,
  currentTopic: '',
  currentRules: '',
  editingAgentId: null,
  sysEdited: false,
  micActive: false,
}

const _subs = {}

function getState(key) {
  if (key) return _state[key]
  return { ..._state }
}

function setState(patch) {
  Object.assign(_state, patch)
  Object.keys(patch).forEach(k =>
    (_subs[k] || []).forEach(fn => fn(_state[k], k))
  )
}

function subscribe(key, fn) {
  (_subs[key] ||= []).push(fn)
}

// Global verfuegbar machen (kein ES Module noetig)
window.AppState = { getState, setState, subscribe }

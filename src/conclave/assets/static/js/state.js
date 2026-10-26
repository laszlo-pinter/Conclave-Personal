// static/js/state.js — Zentraler State mit pub/sub
// Ersetzt die globalen let-Variablen durch ein reaktives State-Objekt.

// Token aus dem URL-Fragment uebernehmen (#token=…, von `conclave desktop`).
// Fragmente landen nicht in Server-Logs; die Adresszeile wird sofort bereinigt.
// Ein Token aus dem Fragment gehoert zu diesem Server, daher API-URL zuruecksetzen.
function _takeTokenFromFragment() {
  const token = new URLSearchParams(window.location.hash.slice(1)).get('token')
  if (!token) return ''
  history.replaceState(null, '', window.location.pathname + window.location.search)
  try {
    localStorage.setItem('conclave_api_key', token)
    localStorage.removeItem('conclave_api_url')
  } catch {}
  return token
}
const _fragmentToken = _takeTokenFromFragment()

const _state = {
  api: (!_fragmentToken && localStorage.getItem('conclave_api_url')) || window.location.origin,
  apiKey: _fragmentToken || localStorage.getItem('conclave_api_key') || '',
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

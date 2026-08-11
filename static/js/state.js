// static/js/state.js — Zentraler State mit pub/sub
// Ersetzt die globalen let-Variablen durch ein reaktives State-Objekt.

const _state = {
  api: localStorage.getItem('conclave_api_url') || window.location.origin,
  apiKey: localStorage.getItem('conclave_api_key') || '',
  currentConvId: null,
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

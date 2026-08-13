// static/js/api.js — API-Client (extrahiert aus conclave-ui.html)

function authHeaders() {
  const h = {'Content-Type': 'application/json'}
  if (AppState.getState('apiKey')) h['Authorization'] = 'Bearer ' + AppState.getState('apiKey')
  return h
}

async function req(method, path, body) {
  const API = AppState.getState('api')
  const opts = {method, headers: authHeaders()}
  if (body !== undefined) opts.body = JSON.stringify(body)
  let res
  try {
    res = await fetch(API + path, opts)
  } catch(e) {
    throw new Error(`Server nicht erreichbar (${API}). Docker laeuft? → ${e.message}`)
  }
  if (res.status === 204) return null
  const text = await res.text()
  if (!text) return null
  let data
  try { data = JSON.parse(text) } catch { throw new Error(`Server-Fehler (HTTP ${res.status}): ${text.slice(0,200)}`) }
  if (!res.ok) {
    const msg = data.error || `HTTP ${res.status}`
    const hint = res.status===401 ? ' → API-Key pruefen'
               : res.status===403 ? ' → Berechtigung fehlt'
               : res.status===502 ? ' → Adapter/Provider-Fehler' : ''
    throw new Error(`${msg}${hint}`)
  }
  return data
}

async function checkApi() {
  const API = AppState.getState('api')
  const dot = document.getElementById('apiDot')
  const lbl = document.getElementById('apiLabel')
  if (!dot || !lbl) return
  try {
    const res = await fetch(API + '/conversations', {headers: authHeaders()})
    if (res.status === 401) {
      dot.className = 'api-dot auth'
      lbl.textContent = 'Auth fehlgeschlagen'
    } else {
      dot.className = 'api-dot ok'
      lbl.textContent = 'API verbunden'
    }
  } catch {
    dot.className = 'api-dot err'
    lbl.textContent = 'API nicht erreichbar'
  }
}

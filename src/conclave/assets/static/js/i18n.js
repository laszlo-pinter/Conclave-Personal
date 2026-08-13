// static/js/i18n.js — Minimal UI localization for the desktop frontend.

const I18N_DEFAULT_LANG = 'de';
const I18N_SUPPORTED_LANGS = ['de', 'en'];

const I18N = {
  de: {
    'lang.label': 'Sprache',
    'lang.de': 'Deutsch',
    'lang.en': 'English',
    'common.loading': 'Lade...',
    'common.cancel': 'Abbrechen',
    'common.save': 'Speichern',
    'common.create': 'Erstellen',
    'common.start': 'Starten',
    'common.delete': 'Loeschen',
    'common.ready': 'Bereit.',
    'common.none': 'Keine',
    'common.requiredIdName': 'ID und Name erforderlich',
    'common.apiUnreachable': 'API nicht erreichbar',
    'common.noData': 'Keine Daten.',
    'common.errorPrefix': 'Fehler',
    'nav.studio': 'Studio',
    'nav.agents': 'Agents',
    'nav.files': 'Files',
    'nav.runs': 'Runs',
    'nav.settings': 'Settings',
    'conv.new': 'Neue Conversation',
    'conv.none': 'Noch keine Conversations',
    'conv.noneSelected': 'Kein Gespraech gewaehlt',
    'conv.selectOrCreate': 'Waehle eine Conversation oder erstelle eine neue.',
    'conv.created': 'Conversation erstellt',
    'conv.deleted': 'Geloescht',
    'conv.missing': 'Conversation nicht mehr vorhanden',
    'conv.chooseFirst': 'Zuerst Conversation waehlen',
    'conv.choose': 'Conversation waehlen, dann:',
    'topic.set': 'Thema setzen',
    'topic.editTitle': 'Thema bearbeiten',
    'topic.label': 'Thema',
    'topic.optional': 'Thema (optional)',
    'topic.hint': 'Schraenkt das Gespraech thematisch ein.',
    'topic.removed': 'Thema entfernt',
    'rules.button': 'Regeln',
    'rules.title': 'Chat-Regeln',
    'rules.modalLabel': 'Regeln fuer alle Agenten in dieser Conversation',
    'rules.hint': 'Werden als System-Instruktion an alle Agenten gesendet, bevor sie antworten.',
    'rules.saved': 'Chat-Regeln gespeichert',
    'rules.removed': 'Chat-Regeln entfernt',
    'floor.label': 'Wort erteilt',
    'floor.grant': 'Wort erteilen:',
    'floor.invoke': 'Antworten lassen',
    'floor.revoke': 'Entziehen',
    'floor.hasFloor': '{name} hat das Wort',
    'floor.revoked': 'Rederecht entzogen',
    'floor.noParticipant': 'Kein Participant hat das Wort',
    'floor.answering': 'Antwortet...',
    'agents.new': 'Neuer Agent',
    'agents.loading': 'Lade Agenten...',
    'agents.none': 'Noch keine Agenten.',
    'agents.title': 'Agents',
    'agents.subtitle': 'Wiederverwendbare Rollen, Provider und Modelle.',
    'agents.listTitle': 'Agenten',
    'agents.providers': 'Provider',
    'agents.providersLoading': 'Lade Provider...',
    'agents.noProviders': 'Keine Provider gefunden.',
    'agents.ready': 'bereit',
    'agents.keyMissing': 'Key fehlt',
    'agents.topicPrefix': 'Thema',
    'agents.modalTitleCreate': 'Agent konfigurieren',
    'agents.modalTitleEdit': 'Agent bearbeiten',
    'agents.id': 'ID *',
    'agents.name': 'Name *',
    'agents.preset': 'Preset',
    'agents.model': 'Modell *',
    'agents.apiKey': 'API-Key',
    'agents.keyHint': 'Wird verschluesselt gespeichert. Ollama braucht keinen Key.',
    'agents.role': 'Rolle (optional)',
    'agents.systemPrompt': 'System-Prompt',
    'agents.advancedShow': 'Erweitert anzeigen',
    'agents.advancedHide': 'Erweitert ausblenden',
    'agents.apiUrl': 'API-URL',
    'agents.responsePath': 'Response-Path',
    'agents.messageFormat': 'Message-Format',
    'agents.urlFromPreset': 'Wird vom Preset gesetzt',
    'agents.emptyKeyFallback': 'Leer = Env-Var Fallback',
    'agents.modelInput': 'Modell eingeben...',
    'agents.recommended': 'Empfohlen',
    'agents.created': 'Agent erstellt',
    'agents.updated': 'Agent aktualisiert',
    'agents.deleted': 'Agent geloescht',
    'agents.test': 'Testen',
    'agents.testing': 'Teste...',
    'agents.testFailed': 'Test fehlgeschlagen: {message}',
    'participants.add': 'Participant',
    'participants.title': 'Participant hinzufuegen',
    'participants.chooseAgent': 'Aus Agenten waehlen',
    'participants.manual': '— Manuell eingeben —',
    'participants.pick': 'Participant waehlen...',
    'participants.noModel': 'Kein Model-Participant',
    'participants.id': 'Participant ID *',
    'participants.name': 'Name *',
    'participants.type': 'Typ',
    'participants.register': 'Registrieren',
    'participants.registered': '{name} registriert',
    'participants.chooseRequired': 'Bitte Participant waehlen',
    'workspace.title': 'Workspace',
    'workspace.subtitle': 'Lokale Dateien, Notizen und Outputs.',
    'workspace.files': 'Dateien',
    'workspace.loading': 'Lade Workspace...',
    'workspace.none': 'Keine Dateien im Workspace.',
    'workspace.upload': 'Datei hochladen',
    'workspace.uploadShort': 'Hochladen',
    'workspace.text': 'Text ablegen',
    'workspace.info': 'Im Chat mit <code>@workspace/datei.md</code> referenzieren. Klick auf Dateiname fuegt Referenz ein.',
    'workspace.export': 'Export',
    'workspace.exportConv': 'Conversation exportieren',
    'workspace.noConversation': 'Keine Conversation gewaehlt',
    'workspace.exportDownloaded': 'Export heruntergeladen',
    'workspace.textTitle': 'Text im Workspace ablegen',
    'workspace.fileName': 'Dateiname',
    'workspace.content': 'Inhalt',
    'workspace.contentPlaceholder': 'Inhalt hier einfuegen...',
    'workspace.fileNameRequired': 'Dateiname erforderlich',
    'workspace.fileTooLarge': 'Datei zu gross (max 512 KB)',
    'workspace.uploaded': '{name} hochgeladen',
    'workspace.saved': '{name} gespeichert',
    'workspace.inserted': '{ref} eingefuegt',
    'workspace.attached': '{name} angehaengt',
    'workspace.readFailed': 'Datei konnte nicht gelesen werden',
    'workspace.filePrefix': 'Datei',
    'runs.recent': 'Letzte Runs',
    'runs.none': 'Noch keine Runs.',
    'runs.title': 'Runs',
    'runs.subtitle': 'Aufrufe, Orchestrierungen und Token-Nutzung.',
    'runs.history': 'Run-Historie',
    'runs.usageByConversation': 'Usage pro Conversation',
    'runs.type': 'Typ',
    'runs.participants': 'Participants',
    'runs.error': 'Fehler',
    'settings.operation': 'Betrieb',
    'settings.title': 'Settings',
    'settings.subtitle': 'Lokale Pfade, API-Zugang und Backups.',
    'settings.runtime': 'Runtime',
    'settings.localWorkspace': 'Lokaler Workspace',
    'settings.workspacePath': 'Workspace-Pfad',
    'settings.backup': 'Backup',
    'settings.createBackup': 'Backup erstellen',
    'settings.backupRunning': 'Backup laeuft...',
    'settings.backupCreated': 'Backup erstellt',
    'settings.apiAccess': 'API-Zugang',
    'settings.apiAuth': 'API Auth',
    'settings.mode': 'Modus',
    'settings.server': 'Server',
    'settings.database': 'Datenbank',
    'settings.dbPath': 'DB-Pfad',
    'settings.authOn': 'An',
    'settings.authOff': 'Aus',
    'settings.keySet': 'gesetzt',
    'settings.keyEmpty': 'leer',
    'settings.workspaceRequired': 'Workspace-Pfad ist erforderlich',
    'settings.workspaceSaved': 'Workspace-Pfad gespeichert',
    'auth.keySet': 'API-Key gesetzt',
    'auth.setKey': 'API-Key setzen',
    'auth.modalTitle': 'API-Key Einstellungen',
    'auth.serverUrl': 'API-Server URL',
    'auth.serverDefault': 'Standard: http://localhost:8000',
    'auth.keyLabel': 'API-Key (Bearer Token)',
    'auth.keyPlaceholder': 'Leer lassen wenn keine Auth noetig',
    'auth.keyHint': 'Wird lokal im Browser gespeichert (LocalStorage). Wird als Authorization: Bearer Header gesendet.',
    'auth.clear': 'Key loeschen',
    'auth.saved': 'Einstellungen gespeichert',
    'auth.removed': 'API-Key entfernt',
    'auth.failed': 'Auth fehlgeschlagen',
    'auth.connected': 'API verbunden',
    'auth.checkKey': 'API-Key pruefen',
    'auth.permissionMissing': 'Berechtigung fehlt',
    'auth.providerError': 'Adapter/Provider-Fehler',
    'input.placeholder': 'Nachricht schreiben...',
    'input.attachTitle': 'Datei anhaengen',
    'input.micTitle': 'Spracheingabe',
    'input.invoke': 'Aufrufen',
    'input.stream': 'Stream',
    'input.orchestrate': 'Orchestrieren',
    'input.autoloop': 'Auto-Loop',
    'input.writeFirst': 'Bitte zuerst eine Nachricht schreiben.',
    'input.answerReceived': 'Antwort erhalten',
    'input.streamDone': 'Stream abgeschlossen',
    'input.idsRequired': 'Bitte IDs eingeben',
    'input.answers': '{count} Antwort(en){parallel}',
    'autoloop.title': 'Auto-Loop — Agenten diskutieren lassen',
    'autoloop.sequence': 'Reihenfolge',
    'autoloop.sequenceHint': 'Komma-getrennte IDs. Diese Sequenz wird pro Runde wiederholt; jeder Agent sieht die Antworten der anderen.',
    'autoloop.maxRounds': 'Max. Runden',
    'autoloop.maxRoundsHint': 'Notbremse, falls kein Stop-Signal kommt.',
    'autoloop.stopSignal': 'Stop-Signal',
    'autoloop.stopSignalHint': 'Sobald ein Agent das schreibt, endet die Diskussion.',
    'autoloop.tip': 'Tipp: Hinterlege unter <b>Regeln</b> eine Anweisung wie &bdquo;Diskutiert miteinander und schreibt <code>@done</code> bei Konsens&ldquo;, damit die Runde sinnvoll endet.',
    'autoloop.start': 'Diskussion starten',
    'autoloop.needOne': 'Bitte mindestens eine Participant-ID angeben',
    'autoloop.starting': 'Auto-Loop startet...',
    'autoloop.finished': 'Auto-Loop beendet',
    'autoloop.running': 'Auto-Loop laeuft — bis zu {rounds} Runden, Stop bei "{signal}"',
    'autoloop.thinking': 'Runde {round} — {name} denkt nach...',
    'autoloop.round': 'Runde {round}',
    'autoloop.signal': 'Konsens erreicht — "{signal}" in Runde {round}',
    'autoloop.maxReached': 'Maximale Rundenzahl ({rounds}) erreicht',
    'autoloop.abort': 'Abbruch: {message}',
    'autoloop.ended': 'Beendet',
    'orch.title': 'Orchestrierung',
    'orch.sequence': 'Reihenfolge',
    'orch.sequenceHint': 'Komma-getrennte IDs. Wiederholungen moeglich.',
    'orch.parallel': 'Parallel ausfuehren (alle gleichzeitig, ohne gegenseitigen Kontext)',
    'copy.title': 'ID kopieren',
    'copy.fullConv': 'Volle ID kopieren: {id}',
    'copy.copied': '{label} kopiert: {id}',
    'copy.failed': 'Kopieren fehlgeschlagen ({message})',
    'download.response': 'Antwort herunterladen',
    'download.done': '{name} #{seq} heruntergeladen',
    'speech.error': 'Sprache: {error}',
    'speech.unavailable': 'Spracheingabe nicht verfuegbar (Chrome/Edge noetig)',
    'speech.recording': 'Aufnahme laeuft...',
    'api.serverUnreachable': 'Server nicht erreichbar ({api}). Docker laeuft? -> {message}',
    'api.serverError': 'Server-Fehler (HTTP {status}): {text}',
  },
  en: {
    'lang.label': 'Language',
    'lang.de': 'Deutsch',
    'lang.en': 'English',
    'common.loading': 'Loading...',
    'common.cancel': 'Cancel',
    'common.save': 'Save',
    'common.create': 'Create',
    'common.start': 'Start',
    'common.delete': 'Delete',
    'common.ready': 'Ready.',
    'common.none': 'None',
    'common.requiredIdName': 'ID and name are required',
    'common.apiUnreachable': 'API unreachable',
    'common.noData': 'No data.',
    'common.errorPrefix': 'Error',
    'nav.studio': 'Studio',
    'nav.agents': 'Agents',
    'nav.files': 'Files',
    'nav.runs': 'Runs',
    'nav.settings': 'Settings',
    'conv.new': 'New conversation',
    'conv.none': 'No conversations yet',
    'conv.noneSelected': 'No conversation selected',
    'conv.selectOrCreate': 'Select a conversation or create a new one.',
    'conv.created': 'Conversation created',
    'conv.deleted': 'Deleted',
    'conv.missing': 'Conversation no longer exists',
    'conv.chooseFirst': 'Select a conversation first',
    'conv.choose': 'Select a conversation, then:',
    'topic.set': 'Set topic',
    'topic.editTitle': 'Edit topic',
    'topic.label': 'Topic',
    'topic.optional': 'Topic (optional)',
    'topic.hint': 'Keeps the conversation focused on this subject.',
    'topic.removed': 'Topic removed',
    'rules.button': 'Rules',
    'rules.title': 'Chat rules',
    'rules.modalLabel': 'Rules for all agents in this conversation',
    'rules.hint': 'Sent as system instructions before agents answer.',
    'rules.saved': 'Chat rules saved',
    'rules.removed': 'Chat rules removed',
    'floor.label': 'Floor granted',
    'floor.grant': 'Grant floor:',
    'floor.invoke': 'Let answer',
    'floor.revoke': 'Revoke',
    'floor.hasFloor': '{name} has the floor',
    'floor.revoked': 'Floor revoked',
    'floor.noParticipant': 'No participant has the floor',
    'floor.answering': 'Answering...',
    'agents.new': 'New agent',
    'agents.loading': 'Loading agents...',
    'agents.none': 'No agents yet.',
    'agents.title': 'Agents',
    'agents.subtitle': 'Reusable roles, providers, and models.',
    'agents.listTitle': 'Agents',
    'agents.providers': 'Providers',
    'agents.providersLoading': 'Loading providers...',
    'agents.noProviders': 'No providers found.',
    'agents.ready': 'ready',
    'agents.keyMissing': 'key missing',
    'agents.topicPrefix': 'Topic',
    'agents.modalTitleCreate': 'Configure agent',
    'agents.modalTitleEdit': 'Edit agent',
    'agents.id': 'ID *',
    'agents.name': 'Name *',
    'agents.preset': 'Preset',
    'agents.model': 'Model *',
    'agents.apiKey': 'API key',
    'agents.keyHint': 'Stored encrypted. Ollama does not need a key.',
    'agents.role': 'Role (optional)',
    'agents.systemPrompt': 'System prompt',
    'agents.advancedShow': 'Show advanced',
    'agents.advancedHide': 'Hide advanced',
    'agents.apiUrl': 'API URL',
    'agents.responsePath': 'Response path',
    'agents.messageFormat': 'Message format',
    'agents.urlFromPreset': 'Set by preset',
    'agents.emptyKeyFallback': 'Empty = env-var fallback',
    'agents.modelInput': 'Enter model...',
    'agents.recommended': 'Recommended',
    'agents.created': 'Agent created',
    'agents.updated': 'Agent updated',
    'agents.deleted': 'Agent deleted',
    'agents.test': 'Test',
    'agents.testing': 'Testing...',
    'agents.testFailed': 'Test failed: {message}',
    'participants.add': 'Participant',
    'participants.title': 'Add participant',
    'participants.chooseAgent': 'Choose from agents',
    'participants.manual': '— Enter manually —',
    'participants.pick': 'Choose participant...',
    'participants.noModel': 'No model participant',
    'participants.id': 'Participant ID *',
    'participants.name': 'Name *',
    'participants.type': 'Type',
    'participants.register': 'Register',
    'participants.registered': '{name} registered',
    'participants.chooseRequired': 'Choose a participant',
    'workspace.title': 'Workspace',
    'workspace.subtitle': 'Local files, notes, and outputs.',
    'workspace.files': 'Files',
    'workspace.loading': 'Loading workspace...',
    'workspace.none': 'No files in workspace.',
    'workspace.upload': 'Upload file',
    'workspace.uploadShort': 'Upload',
    'workspace.text': 'Add text',
    'workspace.info': 'Reference files in chat with <code>@workspace/file.md</code>. Click a filename to insert a reference.',
    'workspace.export': 'Export',
    'workspace.exportConv': 'Export conversation',
    'workspace.noConversation': 'No conversation selected',
    'workspace.exportDownloaded': 'Export downloaded',
    'workspace.textTitle': 'Add text to workspace',
    'workspace.fileName': 'Filename',
    'workspace.content': 'Content',
    'workspace.contentPlaceholder': 'Paste content here...',
    'workspace.fileNameRequired': 'Filename is required',
    'workspace.fileTooLarge': 'File too large (max 512 KB)',
    'workspace.uploaded': '{name} uploaded',
    'workspace.saved': '{name} saved',
    'workspace.inserted': '{ref} inserted',
    'workspace.attached': '{name} attached',
    'workspace.readFailed': 'File could not be read',
    'workspace.filePrefix': 'File',
    'runs.recent': 'Recent runs',
    'runs.none': 'No runs yet.',
    'runs.title': 'Runs',
    'runs.subtitle': 'Calls, orchestrations, and token usage.',
    'runs.history': 'Run history',
    'runs.usageByConversation': 'Usage by conversation',
    'runs.type': 'Type',
    'runs.participants': 'Participants',
    'runs.error': 'Error',
    'settings.operation': 'Operation',
    'settings.title': 'Settings',
    'settings.subtitle': 'Local paths, API access, and backups.',
    'settings.runtime': 'Runtime',
    'settings.localWorkspace': 'Local workspace',
    'settings.workspacePath': 'Workspace path',
    'settings.backup': 'Backup',
    'settings.createBackup': 'Create backup',
    'settings.backupRunning': 'Backup running...',
    'settings.backupCreated': 'Backup created',
    'settings.apiAccess': 'API access',
    'settings.apiAuth': 'API auth',
    'settings.mode': 'Mode',
    'settings.server': 'Server',
    'settings.database': 'Database',
    'settings.dbPath': 'DB path',
    'settings.authOn': 'On',
    'settings.authOff': 'Off',
    'settings.keySet': 'set',
    'settings.keyEmpty': 'empty',
    'settings.workspaceRequired': 'Workspace path is required',
    'settings.workspaceSaved': 'Workspace path saved',
    'auth.keySet': 'API key set',
    'auth.setKey': 'Set API key',
    'auth.modalTitle': 'API key settings',
    'auth.serverUrl': 'API server URL',
    'auth.serverDefault': 'Default: http://localhost:8000',
    'auth.keyLabel': 'API key (Bearer token)',
    'auth.keyPlaceholder': 'Leave empty if auth is not required',
    'auth.keyHint': 'Stored locally in browser LocalStorage. Sent as Authorization: Bearer header.',
    'auth.clear': 'Delete key',
    'auth.saved': 'Settings saved',
    'auth.removed': 'API key removed',
    'auth.failed': 'Auth failed',
    'auth.connected': 'API connected',
    'auth.checkKey': 'check API key',
    'auth.permissionMissing': 'permission missing',
    'auth.providerError': 'adapter/provider error',
    'input.placeholder': 'Write a message...',
    'input.attachTitle': 'Attach file',
    'input.micTitle': 'Voice input',
    'input.invoke': 'Invoke',
    'input.stream': 'Stream',
    'input.orchestrate': 'Orchestrate',
    'input.autoloop': 'Auto-loop',
    'input.writeFirst': 'Please write a message first.',
    'input.answerReceived': 'Answer received',
    'input.streamDone': 'Stream finished',
    'input.idsRequired': 'Please enter IDs',
    'input.answers': '{count} answer(s){parallel}',
    'autoloop.title': 'Auto-loop — let agents discuss',
    'autoloop.sequence': 'Sequence',
    'autoloop.sequenceHint': 'Comma-separated IDs. This sequence repeats each round; every agent sees the others replies.',
    'autoloop.maxRounds': 'Max rounds',
    'autoloop.maxRoundsHint': 'Safety stop if no stop signal appears.',
    'autoloop.stopSignal': 'Stop signal',
    'autoloop.stopSignalHint': 'The discussion stops when an agent writes this.',
    'autoloop.tip': 'Tip: Add a rule such as &ldquo;Discuss with each other and write <code>@done</code> once consensus is reached&rdquo; so the round can end cleanly.',
    'autoloop.start': 'Start discussion',
    'autoloop.needOne': 'Enter at least one participant ID',
    'autoloop.starting': 'Auto-loop starting...',
    'autoloop.finished': 'Auto-loop finished',
    'autoloop.running': 'Auto-loop running — up to {rounds} rounds, stop at "{signal}"',
    'autoloop.thinking': 'Round {round} — {name} is thinking...',
    'autoloop.round': 'Round {round}',
    'autoloop.signal': 'Consensus reached — "{signal}" in round {round}',
    'autoloop.maxReached': 'Maximum rounds reached ({rounds})',
    'autoloop.abort': 'Stopped: {message}',
    'autoloop.ended': 'Finished',
    'orch.title': 'Orchestration',
    'orch.sequence': 'Sequence',
    'orch.sequenceHint': 'Comma-separated IDs. Repetition is allowed.',
    'orch.parallel': 'Run in parallel (all at once, without shared context)',
    'copy.title': 'Copy ID',
    'copy.fullConv': 'Copy full ID: {id}',
    'copy.copied': '{label} copied: {id}',
    'copy.failed': 'Copy failed ({message})',
    'download.response': 'Download answer',
    'download.done': '{name} #{seq} downloaded',
    'speech.error': 'Voice: {error}',
    'speech.unavailable': 'Voice input unavailable (Chrome/Edge required)',
    'speech.recording': 'Recording...',
    'api.serverUnreachable': 'Server unreachable ({api}). Is Docker running? -> {message}',
    'api.serverError': 'Server error (HTTP {status}): {text}',
  },
};

function getLanguage() {
  const saved = localStorage.getItem('conclave_ui_lang') || I18N_DEFAULT_LANG;
  return I18N_SUPPORTED_LANGS.includes(saved) ? saved : I18N_DEFAULT_LANG;
}

function t(key, vars = {}) {
  const lang = getLanguage();
  const fallback = I18N[I18N_DEFAULT_LANG][key] || key;
  let text = I18N[lang][key] || fallback;
  Object.entries(vars).forEach(([name, value]) => {
    text = text.replaceAll(`{${name}}`, String(value));
  });
  return text;
}

function applyTranslations(root = document) {
  const lang = getLanguage();
  document.documentElement.lang = lang;
  const select = document.getElementById('languageSelect');
  if (select) select.value = lang;

  root.querySelectorAll('[data-i18n]').forEach(el => {
    el.textContent = t(el.dataset.i18n);
  });
  root.querySelectorAll('[data-i18n-html]').forEach(el => {
    el.innerHTML = t(el.dataset.i18nHtml);
  });
  root.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    el.setAttribute('placeholder', t(el.dataset.i18nPlaceholder));
  });
  root.querySelectorAll('[data-i18n-title]').forEach(el => {
    el.setAttribute('title', t(el.dataset.i18nTitle));
  });
  localizeRuntimeLabels();
}

function _setButtonHtml(id, html) {
  const el = document.getElementById(id);
  if (!el || el.querySelector('.spinner')) return;
  el.innerHTML = html;
}

function localizeRuntimeLabels() {
  _setButtonHtml('btnInvoke', t('input.invoke'));
  _setButtonHtml('btnStream', `&#9654; ${t('input.stream')}`);
  _setButtonHtml('btnOrch', `&#8635; ${t('input.orchestrate')}`);
  _setButtonHtml('btnAutoloop', `&#8734; ${t('input.autoloop')}`);
  _setButtonHtml('btnFloorInvoke', t('floor.invoke'));

  const advanced = document.getElementById('advancedFields');
  const advancedBtn = document.getElementById('btnAdvanced');
  if (advanced && advancedBtn && !advancedBtn.querySelector('.spinner')) {
    advancedBtn.textContent = advanced.style.display === 'none'
      ? t('agents.advancedShow')
      : t('agents.advancedHide');
  }

  const saveAgentLabel = document.getElementById('btnSaveAgentLabel');
  if (saveAgentLabel && !saveAgentLabel.querySelector('.spinner')) {
    saveAgentLabel.textContent = t('common.save');
  }

  const testAgent = document.getElementById('btnTestAgent');
  if (testAgent && !testAgent.querySelector('.spinner') && !testAgent.disabled) {
    testAgent.textContent = t('agents.test');
  }

  const agentTitle = document.getElementById('agentModalTitle');
  if (agentTitle && typeof editingAgentId !== 'undefined') {
    agentTitle.textContent = editingAgentId ? t('agents.modalTitleEdit') : t('agents.modalTitleCreate');
  }
}

function refreshLocalizedUI() {
  applyTranslations();
  if (typeof updateKeyUI === 'function') updateKeyUI();
  if (typeof checkApi === 'function') checkApi();
  if (typeof renderConvList === 'function') renderConvList();
  if (typeof renderAgentList === 'function') renderAgentList();
  if (typeof renderAgentWorkbench === 'function') renderAgentWorkbench();
  if (typeof renderBadges === 'function') renderBadges();
  if (typeof renderTopicUI === 'function') renderTopicUI();
  if (typeof renderFloorUI === 'function') renderFloorUI();
  if (typeof updatePrompt === 'function' && typeof sysEdited !== 'undefined' && !sysEdited) updatePrompt();
  const active = document.querySelector('.sb-tab.active')?.dataset.tab;
  if (active === 'agents' && typeof loadProviders === 'function') loadProviders();
  if (active === 'workspace' && typeof loadWorkspace === 'function') loadWorkspace();
  if (active === 'runs') {
    if (typeof loadRuns === 'function') loadRuns();
    if (typeof loadConversationUsage === 'function') loadConversationUsage();
  }
  if (active === 'settings' && typeof loadSettings === 'function') loadSettings();
}

function setLanguage(lang) {
  if (!I18N_SUPPORTED_LANGS.includes(lang)) return;
  localStorage.setItem('conclave_ui_lang', lang);
  refreshLocalizedUI();
}

function initI18n() {
  applyTranslations();
}

window.t = t;
window.getLanguage = getLanguage;
window.setLanguage = setLanguage;
window.initI18n = initI18n;
window.applyTranslations = applyTranslations;

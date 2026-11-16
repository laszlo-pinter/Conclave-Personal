// static/js/theme.js — heller und dunkler Modus (conclave#62)
// "system" folgt prefers-color-scheme; "light"/"dark" setzen data-theme auf <html>.

const THEME_KEY = 'conclave_ui_theme';
const THEMES = ['system', 'light', 'dark'];

function getTheme() {
  try {
    const saved = localStorage.getItem(THEME_KEY);
    return THEMES.includes(saved) ? saved : 'system';
  } catch { return 'system'; }
}

function applyTheme() {
  const theme = getTheme();
  if (theme === 'system') delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme;
  const select = document.getElementById('themeSelect');
  if (select) select.value = theme;
}

function setTheme(theme) {
  if (!THEMES.includes(theme)) return;
  try { localStorage.setItem(THEME_KEY, theme); } catch { /* nur fuer diese Sitzung */ }
  applyTheme();
}

applyTheme();                                         // im <head>: kein Aufblitzen des falschen Modus
document.addEventListener('DOMContentLoaded', applyTheme);

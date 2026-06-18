(function () {
  var STORAGE_KEY = 'lojaonline_theme';
  var THEME_VARS = {
    dark: {
      '--bg': '#0f0f14',
      '--surface': '#1a1a28',
      '--side': '#13131f',
      '--line': '#2a2a40',
      '--text': '#e8e8f0',
      '--muted': '#888fa0',
      '--purple': '#7c3aed',
      '--green': '#10b981',
      '--amber': '#f59e0b',
      '--livre': '#2a2a40',
      '--danger': '#f87171',
      '--input-bg': '#10101a',
      '--control-bg': '#151522',
      '--btn-secondary': '#171726',
      '--collapse-bg': '#141422',
      '--accent-soft': '#ddd6fe',
      '--tab-active': '#e9d5ff',
      '--outline-fg': '#ddd6fe',
      '--pay-selected-fg': '#d1fae5',
      '--sum-open': '#c4b5fd',
      '--on-primary': '#fff'
    },
    light: {
      '--bg': '#f1f5f9',
      '--surface': '#ffffff',
      '--side': '#e8ecf4',
      '--line': '#c8d0e0',
      '--text': '#0f172a',
      '--muted': '#64748b',
      '--purple': '#6d28d9',
      '--green': '#059669',
      '--amber': '#d97706',
      '--livre': '#cbd5e1',
      '--danger': '#dc2626',
      '--input-bg': '#f8fafc',
      '--control-bg': '#e2e8f0',
      '--btn-secondary': '#eef2f7',
      '--collapse-bg': '#f8fafc',
      '--accent-soft': '#5b21b6',
      '--tab-active': '#5b21b6',
      '--outline-fg': '#5b21b6',
      '--pay-selected-fg': '#065f46',
      '--sum-open': '#6d28d9',
      '--on-primary': '#fff'
    }
  };

  function applyVars(theme) {
    var t = theme === 'light' ? 'light' : 'dark';
    var vars = THEME_VARS[t];
    try {
      Object.keys(vars).forEach(function (k) {
        document.documentElement.style.setProperty(k, vars[k]);
      });
    } catch (_) {}
  }

  function getStoredTheme() {
    try {
      var v = localStorage.getItem(STORAGE_KEY);
      if (v === 'light' || v === 'dark') return v;
    } catch (_) {}
    return 'dark';
  }

  function applyTheme(name) {
    var t = name === 'light' ? 'light' : 'dark';
    try {
      localStorage.setItem(STORAGE_KEY, t);
    } catch (_) {}
    document.documentElement.setAttribute('data-theme', t);
    applyVars(t);
    try {
      document.dispatchEvent(new CustomEvent('lojaonline-theme', { detail: { theme: t } }));
    } catch (_) {}
  }

  function toggleTheme() {
    applyTheme(getStoredTheme() === 'light' ? 'dark' : 'light');
    return getStoredTheme();
  }

  function initTheme() {
    var t = getStoredTheme();
    document.documentElement.setAttribute('data-theme', t);
    applyVars(t);
    return t;
  }

  window.LojaOnlineTheme = {
    STORAGE_KEY: STORAGE_KEY,
    getStoredTheme: getStoredTheme,
    applyTheme: applyTheme,
    toggleTheme: toggleTheme,
    initTheme: initTheme
  };

  function bindButtons() {
    try { initTheme(); } catch (_) {}
    try { if (window.lucide && window.lucide.createIcons) window.lucide.createIcons(); } catch (_) {}
    try {
      var btn = document.getElementById('theme-toggle');
      if (!btn || btn.getAttribute('data-lo-theme-bound') === '1') return;
      btn.setAttribute('data-lo-theme-bound', '1');
      btn.addEventListener('click', function () {
        try { toggleTheme(); } catch (_) {}
        try { if (window.lucide && window.lucide.createIcons) window.lucide.createIcons(); } catch (_) {}
      });
    } catch (_) {}
  }

  try {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', bindButtons);
    } else {
      bindButtons();
    }
  } catch (_) {}

  try {
    var obs = new MutationObserver(function () {
      try { applyVars(document.documentElement.getAttribute('data-theme')); } catch (_) {}
    });
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  } catch (_) {}
})();

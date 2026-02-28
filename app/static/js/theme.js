/**
 * ArdavFact — Toggle de tema claro/oscuro
 * IMPORTANTE: este script debe cargarse en el <head> (antes de renderizar)
 * para evitar el flash de tema incorrecto.
 */
(function () {
  const STORAGE_KEY = 'af-theme';
  const saved = localStorage.getItem(STORAGE_KEY);
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const theme = saved || (prefersDark ? 'dark' : 'light');

  document.documentElement.setAttribute('data-theme', theme);

  function applyTheme(t) {
    document.documentElement.setAttribute('data-theme', t);
    localStorage.setItem(STORAGE_KEY, t);

    const btn = document.getElementById('theme-toggle');
    if (btn) {
      btn.querySelector('i').className = t === 'dark'
        ? 'bi bi-sun-fill'
        : 'bi bi-moon-stars-fill';
      btn.title = t === 'dark' ? 'Cambiar a tema claro' : 'Cambiar a tema oscuro';
    }
  }

  // Aplica al cargar
  document.addEventListener('DOMContentLoaded', function () {
    applyTheme(localStorage.getItem(STORAGE_KEY) || theme);

    const btn = document.getElementById('theme-toggle');
    if (btn) {
      btn.addEventListener('click', function () {
        const current = document.documentElement.getAttribute('data-theme');
        applyTheme(current === 'dark' ? 'light' : 'dark');
      });
    }
  });
})();

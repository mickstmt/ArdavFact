/**
 * ArdavFact — Helpers JS compartidos
 */

/** Formatea un número como moneda peruana (S/ 1,234.56) */
function formatMoney(amount) {
  return 'S/ ' + parseFloat(amount || 0).toLocaleString('es-PE', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/** Obtiene el CSRF token del meta tag para peticiones AJAX */
function getCsrfToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? meta.getAttribute('content') : '';
}

/**
 * Wrapper para fetch con CSRF y JSON automático.
 * Uso: await afFetch('/api/endpoint', { method: 'POST', body: { key: val } })
 */
async function afFetch(url, options = {}) {
  const defaults = {
    method: 'GET',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': getCsrfToken(),
    },
  };

  if (options.body && typeof options.body === 'object') {
    options.body = JSON.stringify(options.body);
  }

  const response = await fetch(url, Object.assign({}, defaults, options, {
    headers: Object.assign({}, defaults.headers, options.headers || {}),
  }));

  if (!response.ok) {
    const fallback = response.status === 400 ? 'La sesión ha expirado. Recarga la página.'
                   : response.status === 401 ? 'Tu sesión ha expirado. Inicia sesión nuevamente.'
                   : response.status === 403 ? 'Sin permisos para esta acción.'
                   : 'Error desconocido';
    const err = await response.json().catch(() => ({ message: fallback }));
    throw new Error(err.message || fallback);
  }

  return response.json();
}

/** Spinner en un botón durante operación async */
function btnLoading(btn, text = 'Procesando...') {
  btn._originalHTML = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = `<span class="spinner-border spinner-border-sm me-1" role="status"></span>${text}`;
}

function btnRestore(btn) {
  if (btn._originalHTML) {
    btn.innerHTML = btn._originalHTML;
    btn.disabled = false;
  }
}

/** Debounce para búsquedas en tiempo real */
function debounce(fn, delay = 300) {
  let timer;
  return function (...args) {
    clearTimeout(timer);
    timer = setTimeout(() => fn.apply(this, args), delay);
  };
}

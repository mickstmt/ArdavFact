/**
 * ArdavFact — Sistema de notificaciones Toast
 *
 * Uso:
 *   showToast('Éxito', 'Comprobante enviado a SUNAT.', 'success')
 *   showToast('Error', 'No se pudo conectar.', 'danger')
 *   showToast('Aviso', 'Revisa los campos.', 'warning')
 *   showToast('Info', 'Sincronización en curso.', 'info')
 */

const TOAST_ICONS = {
  success: 'bi-check-circle-fill',
  danger:  'bi-x-circle-fill',
  warning: 'bi-exclamation-triangle-fill',
  info:    'bi-info-circle-fill',
};

function showToast(title, message, type = 'info', duration = 4500, url = null) {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `af-toast toast-${type}`;
  if (url) toast.style.cursor = 'pointer';

  const icon = TOAST_ICONS[type] || 'bi-bell-fill';

  toast.innerHTML = `
    <i class="bi ${icon}" style="color: var(--bs-${type === 'danger' ? 'danger' : type === 'success' ? 'success' : type === 'warning' ? 'warning' : 'info'}); flex-shrink:0; margin-top:1px;"></i>
    <div style="flex:1; min-width:0;">
      <div class="af-toast-title">${title}</div>
      ${message ? `<div class="af-toast-msg">${message}</div>` : ''}
      ${url ? `<div class="af-toast-msg" style="opacity:0.7;font-size:0.75em;">Click para ver detalle</div>` : ''}
    </div>
    <button class="af-toast-close" onclick="event.stopPropagation();this.closest('.af-toast').remove()" aria-label="Cerrar">
      <i class="bi bi-x"></i>
    </button>
  `;

  if (url) {
    toast.addEventListener('click', () => window.location.href = url);
  }

  container.appendChild(toast);

  if (duration > 0) {
    setTimeout(() => {
      toast.style.animation = 'toastOut 0.25s ease forwards';
      setTimeout(() => toast.remove(), 250);
    }, duration);
  }
}

/**
 * Muestra los flash messages de Flask como toasts al cargar la página.
 * Requiere que base.html inyecte los flashes en window.AF_FLASHES.
 */
document.addEventListener('DOMContentLoaded', function () {
  if (window.AF_FLASHES && Array.isArray(window.AF_FLASHES)) {
    window.AF_FLASHES.forEach(function (f) {
      const typeMap = { success: 'success', danger: 'danger', warning: 'warning', info: 'info', error: 'danger' };
      const titleMap = { success: 'Éxito', danger: 'Error', warning: 'Aviso', info: 'Información', error: 'Error' };
      const t = typeMap[f.category] || 'info';
      showToast(titleMap[t] || 'Aviso', f.message, t);
    });
  }
});

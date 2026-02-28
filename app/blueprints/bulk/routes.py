"""Rutas de carga masiva desde Excel de WooCommerce."""
import os
import uuid

from flask import (
    render_template, request, jsonify, current_app,
    redirect, url_for, flash,
)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from app.decorators import requiere_permiso
from app.services import bulk_service
from . import bulk_bp

_ALLOWED_EXT = {'xlsx', 'xls'}


def _allowed(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in _ALLOWED_EXT


# ─────────────────────────────────────────────────────────────────────────────
# Upload
# ─────────────────────────────────────────────────────────────────────────────

@bulk_bp.route('/', methods=['GET'])
@login_required
@requiere_permiso('ventas.crear')
def upload():
    """Formulario de carga masiva."""
    return render_template('bulk/upload.html')


@bulk_bp.route('/analizar', methods=['POST'])
@login_required
@requiere_permiso('ventas.crear')
def analizar():
    """Recibe el Excel, lo analiza y devuelve el preview en JSON."""
    if 'archivo' not in request.files:
        return jsonify({'success': False, 'message': 'No se recibió archivo.'}), 400

    archivo = request.files['archivo']
    if not archivo.filename or not _allowed(archivo.filename):
        return jsonify({'success': False, 'message': 'Formato no válido. Use .xlsx o .xls.'}), 400

    # Guardar temporalmente
    uploads_path = current_app.config.get('UPLOADS_PATH', 'uploads')
    os.makedirs(uploads_path, exist_ok=True)
    nombre_temp = f'bulk_{uuid.uuid4().hex}.xlsx'
    ruta_temp = os.path.join(uploads_path, nombre_temp)

    try:
        archivo.save(ruta_temp)
        ordenes = bulk_service.analizar_excel(ruta_temp, current_app.config)
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception as exc:
        current_app.logger.error('[BULK] Error analizando Excel: %s', exc, exc_info=True)
        return jsonify({'success': False, 'message': f'Error al procesar el archivo: {exc}'}), 500
    finally:
        if os.path.exists(ruta_temp):
            os.remove(ruta_temp)

    total_ok      = sum(1 for o in ordenes if o['status'] == 'OK')
    total_warning = sum(1 for o in ordenes if o['status'] == 'WARNING')
    total_error   = sum(1 for o in ordenes if o['status'] == 'ERROR')

    return jsonify({
        'success': True,
        'ordenes': ordenes,
        'resumen': {
            'total':   len(ordenes),
            'ok':      total_ok,
            'warning': total_warning,
            'error':   total_error,
        },
    })


# ─────────────────────────────────────────────────────────────────────────────
# Preview (página HTML)
# ─────────────────────────────────────────────────────────────────────────────

@bulk_bp.route('/preview', methods=['GET'])
@login_required
@requiere_permiso('ventas.crear')
def preview():
    """Página de preview (la tabla se carga vía JS con datos del localStorage)."""
    return render_template('bulk/preview.html')


# ─────────────────────────────────────────────────────────────────────────────
# Procesar
# ─────────────────────────────────────────────────────────────────────────────

@bulk_bp.route('/procesar', methods=['POST'])
@login_required
@requiere_permiso('ventas.crear')
def procesar():
    """Crea comprobantes para las órdenes seleccionadas (OK y WARNING)."""
    payload = request.get_json(force=True) or {}
    ordenes = payload.get('ordenes', [])

    if not ordenes:
        return jsonify({'success': False, 'message': 'Sin órdenes para procesar.'}), 400

    try:
        resultados = bulk_service.procesar_ordenes(
            ordenes,
            current_app.config,
            vendedor_id=current_user.id,
        )
    except Exception as exc:
        current_app.logger.error('[BULK] Error en procesar: %s', exc, exc_info=True)
        return jsonify({'success': False, 'message': f'Error interno: {exc}'}), 500

    exitosos = sum(1 for r in resultados if r.get('success'))
    fallidos  = len(resultados) - exitosos

    return jsonify({
        'success': True,
        'message': f'{exitosos} comprobante(s) creado(s), {fallidos} error(es).',
        'resultados': resultados,
        'exitosos': exitosos,
        'fallidos': fallidos,
    })

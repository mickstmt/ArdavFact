"""Rutas de carga masiva desde Excel de Falabella."""
import os
import uuid

from flask import (
    render_template, request, jsonify, current_app,
)
from flask_login import login_required, current_user

from app.decorators import requiere_permiso
from app.services import bulk_falabella_service
from app.services.bulk_service import procesar_ordenes
from app.blueprints.bulk.routes import descargar_errores as _descargar_errores_shared
from . import bulk_falabella_bp

_ALLOWED_EXT = {'xlsx', 'xls'}


def _allowed(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in _ALLOWED_EXT


@bulk_falabella_bp.route('/', methods=['GET'])
@login_required
@requiere_permiso('ventas.crear')
def upload():
    return render_template('bulk_falabella/upload.html')


@bulk_falabella_bp.route('/analizar', methods=['POST'])
@login_required
@requiere_permiso('ventas.crear')
def analizar():
    if 'archivo' not in request.files:
        return jsonify({'success': False, 'message': 'No se recibió archivo.'}), 400

    archivo = request.files['archivo']
    if not archivo.filename or not _allowed(archivo.filename):
        return jsonify({'success': False, 'message': 'Formato no válido. Use .xlsx o .xls.'}), 400

    uploads_path = current_app.config.get('UPLOADS_PATH', 'uploads')
    os.makedirs(uploads_path, exist_ok=True)
    nombre_temp = f'bulk_fal_{uuid.uuid4().hex}.xlsx'
    ruta_temp = os.path.join(uploads_path, nombre_temp)

    try:
        archivo.save(ruta_temp)
        ordenes = bulk_falabella_service.analizar_excel(ruta_temp, current_app.config)
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception as exc:
        current_app.logger.error('[BULK-FAL] Error analizando Excel: %s', exc, exc_info=True)
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


@bulk_falabella_bp.route('/preview', methods=['GET'])
@login_required
@requiere_permiso('ventas.crear')
def preview():
    return render_template('bulk_falabella/preview.html')


@bulk_falabella_bp.route('/procesar', methods=['POST'])
@login_required
@requiere_permiso('ventas.crear')
def procesar():
    payload = request.get_json(force=True) or {}
    ordenes = payload.get('ordenes', [])
    fecha_override = (payload.get('fecha_override') or '').strip() or None

    if not ordenes:
        return jsonify({'success': False, 'message': 'Sin órdenes para procesar.'}), 400

    try:
        resultados = procesar_ordenes(
            ordenes,
            current_app.config,
            vendedor_id=current_user.id,
            fecha_override=fecha_override,
        )
    except Exception as exc:
        current_app.logger.error('[BULK-FAL] Error en procesar: %s', exc, exc_info=True)
        return jsonify({'success': False, 'message': f'Error interno: {exc}'}), 500

    exitosos = sum(1 for r in resultados if r.get('success'))
    fallidos  = len(resultados) - exitosos

    return jsonify({
        'success':    True,
        'message':    f'{exitosos} comprobante(s) creado(s), {fallidos} error(es).',
        'resultados': resultados,
        'exitosos':   exitosos,
        'fallidos':   fallidos,
    })


@bulk_falabella_bp.route('/descargar-errores', methods=['POST'])
@login_required
@requiere_permiso('ventas.crear')
def descargar_errores():
    """Delega al handler compartido forzando fuente=falabella."""
    return _descargar_errores_shared()

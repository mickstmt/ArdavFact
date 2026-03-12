"""Rutas de carga masiva desde Excel (WooCommerce, Falabella, MercadoLibre)."""
import io
import os
import uuid
import base64
from datetime import datetime

from flask import (
    render_template, request, jsonify, current_app,
    redirect, url_for, flash,
)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from app.decorators import requiere_permiso
from app.services import bulk_service, bulk_falabella_service, bulk_meli_service
from . import bulk_bp

_SERVICIOS = {
    'woo':       bulk_service,
    'falabella': bulk_falabella_service,
    'meli':      bulk_meli_service,
}

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

    plataforma = request.form.get('plataforma', 'woo').strip().lower()
    servicio = _SERVICIOS.get(plataforma, bulk_service)

    try:
        archivo.save(ruta_temp)
        ordenes = servicio.analizar_excel(ruta_temp, current_app.config)
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
        'success':    True,
        'plataforma': plataforma,
        'ordenes':    ordenes,
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
    fecha_override = (payload.get('fecha_override') or '').strip() or None

    if not ordenes:
        return jsonify({'success': False, 'message': 'Sin órdenes para procesar.'}), 400

    try:
        resultados = bulk_service.procesar_ordenes(
            ordenes,
            current_app.config,
            vendedor_id=current_user.id,
            fecha_override=fecha_override,
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


# ─────────────────────────────────────────────────────────────────────────────
# Descargar errores
# ─────────────────────────────────────────────────────────────────────────────

@bulk_bp.route('/descargar-errores', methods=['POST'])
@login_required
@requiere_permiso('ventas.crear')
def descargar_errores():
    """Genera Excel con órdenes en ERROR o WARNING para corrección y re-carga."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    payload = request.get_json(force=True) or {}
    ordenes = payload.get('ordenes', [])
    fuente  = payload.get('fuente', 'woo')

    if not ordenes:
        return jsonify({'success': False, 'message': 'Sin datos para exportar.'}), 400

    _FUENTE_NOMBRE = {'woo': 'WooCommerce', 'meli': 'MercadoLibre', 'falabella': 'Falabella'}
    fuente_nombre = _FUENTE_NOMBRE.get(fuente, fuente.capitalize())

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Errores'

    HDR_FILL  = PatternFill('solid', fgColor='FF1e3a5f')
    ERR_FILL  = PatternFill('solid', fgColor='FFF8D7DA')
    WARN_FILL = PatternFill('solid', fgColor='FFFFF3CD')
    THIN      = Side(style='thin', color='CCCCCC')
    BORDER    = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

    hdrs = [
        'Fuente', 'N° Orden', 'Fecha', 'Nombre Cliente', 'N° Documento',
        'SKU', 'Descripción', 'Cantidad', 'Precio Unit. (S/)', 'Costo Envío (S/)',
        'Tipo', 'Detalle del error / advertencia',
    ]
    ws.append(hdrs)
    for col_idx in range(1, len(hdrs) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.font      = Font(bold=True, color='FFFFFFFF', size=10)
        cell.fill      = HDR_FILL
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        cell.border    = BORDER
    ws.row_dimensions[1].height = 28

    col_widths = [14, 22, 12, 28, 16, 18, 36, 10, 16, 16, 12, 50]
    for i, w in enumerate(col_widths, start=1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w

    for orden in ordenes:
        num_orden    = orden.get('numero_orden', '')
        fecha_str    = orden.get('fecha_emision', '')
        if fecha_str and 'T' in fecha_str:
            fecha_str = fecha_str[:10]
        nombre       = orden.get('nombre_cliente', '')
        num_doc      = orden.get('numero_documento', '')
        costo_envio  = float(orden.get('costo_envio', 0) or 0)
        errores_ord  = orden.get('errores', [])
        advertencias = orden.get('advertencias', [])
        items        = orden.get('items', [])
        status       = orden.get('status', 'ERROR')
        row_fill     = ERR_FILL if status == 'ERROR' else WARN_FILL

        if not items:
            # Orden sin ítems — fila única con el error de la orden
            tipo_msg  = status
            detalle   = ' | '.join(errores_ord + advertencias) or '—'
            ws.append([fuente_nombre, num_orden, fecha_str, nombre, num_doc,
                       '—', '—', '', '', costo_envio, tipo_msg, detalle])
            for cell in ws[ws.max_row]:
                cell.fill   = row_fill
                cell.border = BORDER
                cell.alignment = Alignment(vertical='center', wrap_text=True)
            ws.row_dimensions[ws.max_row].height = 18
        else:
            for item in items:
                item_error = item.get('error')
                if item_error:
                    tipo_msg = 'Error ítem'
                    detalle  = item_error
                    fill     = ERR_FILL
                elif errores_ord or advertencias:
                    tipo_msg = 'Advertencia' if status == 'WARNING' else status
                    detalle  = ' | '.join(errores_ord + advertencias)
                    fill     = row_fill
                else:
                    continue  # ítem OK en una orden OK no debería llegar aquí

                ws.append([
                    fuente_nombre,
                    num_orden,
                    fecha_str,
                    nombre,
                    num_doc,
                    item.get('sku', ''),
                    item.get('descripcion', ''),
                    float(item.get('cantidad', 1) or 1),
                    float(item.get('precio_con_igv', 0) or 0),
                    costo_envio,
                    tipo_msg,
                    detalle,
                ])
                for cell in ws[ws.max_row]:
                    cell.fill   = fill
                    cell.border = BORDER
                    cell.alignment = Alignment(vertical='center', wrap_text=True)
                ws.row_dimensions[ws.max_row].height = 18
                # costo_envio sólo en primera fila de la orden
                costo_envio = ''

    ws.freeze_panes = 'A2'

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    b64 = base64.b64encode(output.read()).decode('utf-8')
    nombre_archivo = f'errores_{fuente}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'

    return jsonify({'success': True, 'filename': nombre_archivo, 'filedata': b64})

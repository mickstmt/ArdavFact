"""Rutas de comprobantes: descargas PDF/XML/CDR, reenvío a SUNAT, envío en lote e importación."""
import io
import os
from flask import send_file, abort, jsonify, request, current_app, render_template
from flask_login import login_required
from werkzeug.utils import secure_filename
from app.extensions import db
from app.models.comprobante import Comprobante
from app.services import pdf_service, mipse_service, file_service as file_svc
from app.services.sunat_xml_service import nombre_archivo
from app.decorators import requiere_permiso
from . import comprobantes_bp


# ─────────────────────────────────────────────────────────────────────────────
# PDF
# ─────────────────────────────────────────────────────────────────────────────

@comprobantes_bp.route('/<int:comp_id>/pdf')
@login_required
@requiere_permiso('ventas.ver')
def descargar_pdf(comp_id: int):
    """Genera (o sirve desde caché) el PDF de un comprobante."""
    comp = db.session.get(Comprobante, comp_id)
    if not comp:
        abort(404)

    fs = file_svc.get_file_service()

    if fs.pdf_existe(comp):
        return send_file(
            comp.pdf_path,
            mimetype='application/pdf',
            as_attachment=False,
            download_name=f'{comp.numero_completo}.pdf',
        )

    try:
        pdf_bytes = pdf_service.generar_pdf(comp)
        fs.guardar_pdf(comp, pdf_bytes)
        db.session.commit()
    except Exception as e:
        current_app.logger.error(f'[PDF] Error generando {comp.numero_completo}: {e}', exc_info=True)
        pdf_bytes = pdf_service.generar_pdf(comp)

    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype='application/pdf',
        as_attachment=False,
        download_name=f'{comp.numero_completo}.pdf',
    )


# ─────────────────────────────────────────────────────────────────────────────
# XML
# ─────────────────────────────────────────────────────────────────────────────

@comprobantes_bp.route('/<int:comp_id>/xml')
@login_required
@requiere_permiso('ventas.ver')
def descargar_xml(comp_id: int):
    """Descarga el XML firmado. Si no existe, regenera desde BD (sin firma)."""
    comp = db.session.get(Comprobante, comp_id)
    if not comp:
        abort(404)

    fs = file_svc.get_file_service()

    if fs.xml_existe(comp):
        return send_file(
            comp.xml_path,
            mimetype='application/xml',
            as_attachment=True,
            download_name=f'{nombre_archivo(comp)}.xml',
        )

    xml_bytes = fs.regenerar_xml(comp)
    return send_file(
        io.BytesIO(xml_bytes),
        mimetype='application/xml',
        as_attachment=True,
        download_name=f'{nombre_archivo(comp)}_sin_firma.xml',
    )


# ─────────────────────────────────────────────────────────────────────────────
# CDR
# ─────────────────────────────────────────────────────────────────────────────

@comprobantes_bp.route('/<int:comp_id>/cdr')
@login_required
@requiere_permiso('ventas.ver')
def descargar_cdr(comp_id: int):
    """Descarga el CDR (Constancia de Recepción SUNAT)."""
    comp = db.session.get(Comprobante, comp_id)
    if not comp:
        abort(404)

    fs = file_svc.get_file_service()

    if not fs.cdr_existe(comp):
        return jsonify({'success': False, 'message': 'CDR no disponible.'}), 404

    return send_file(
        comp.cdr_path,
        mimetype='application/xml',
        as_attachment=True,
        download_name=f'R-{nombre_archivo(comp)}.xml',
    )


# ─────────────────────────────────────────────────────────────────────────────
# Reenviar a SUNAT (individual)
# ─────────────────────────────────────────────────────────────────────────────

@comprobantes_bp.route('/<int:comp_id>/reenviar', methods=['POST'])
@login_required
@requiere_permiso('ventas.crear')
def reenviar_sunat(comp_id: int):
    """Reintenta el envío de un comprobante PENDIENTE/RECHAZADO a SUNAT."""
    comp = db.session.get(Comprobante, comp_id)
    if not comp:
        abort(404)

    if comp.estado not in ('PENDIENTE', 'ENVIADO', 'RECHAZADO'):
        return jsonify({
            'success': False,
            'message': f'Estado actual: {comp.estado}. Solo PENDIENTE/ENVIADO/RECHAZADO pueden reenviarse.',
        }), 400

    resultado = mipse_service.procesar_comprobante(comp)
    if resultado['success']:
        fs = file_svc.get_file_service()
        fs.guardar_archivos(comp, resultado)

    db.session.commit()

    if resultado['success']:
        message = f'Enviado. Estado SUNAT: {resultado["estado"]}.'
    else:
        msg_sunat = resultado.get('mensaje_sunat', '')
        # Distinguir error temporal de SUNAT vs. error real
        if 'no responde' in msg_sunat.lower() or 'intenta el reenv' in msg_sunat.lower():
            message = 'SUNAT no está disponible en este momento. El comprobante quedó en PENDIENTE y se reintentará automáticamente esta noche.'
        else:
            message = f'Error: {msg_sunat}'

    return jsonify({
        'success': resultado['success'],
        'message': message,
        'estado': comp.estado,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Envío en lote
# ─────────────────────────────────────────────────────────────────────────────

@comprobantes_bp.route('/enviar-lote', methods=['POST'])
@login_required
@requiere_permiso('ventas.crear')
def enviar_lote():
    """Envía a SUNAT una lista de comprobantes (desde selección en lista)."""
    payload = request.get_json(force=True) or {}
    ids = [int(i) for i in payload.get('ids', []) if str(i).isdigit()]

    if not ids:
        return jsonify({'success': False, 'message': 'Sin comprobantes seleccionados.'}), 400

    comprobantes = Comprobante.query.filter(
        Comprobante.id.in_(ids),
        Comprobante.estado.in_(('PENDIENTE', 'ENVIADO', 'RECHAZADO')),
    ).all()

    enviados = errores = 0
    fs = file_svc.get_file_service()

    for comp in comprobantes:
        resultado = mipse_service.procesar_comprobante(comp)
        if resultado['success']:
            fs.guardar_archivos(comp, resultado)
            enviados += 1
        else:
            errores += 1
        db.session.commit()

    return jsonify({
        'success': True,
        'message': f'{len(comprobantes)} procesados: {enviados} enviados, {errores} con error.',
        'enviados': enviados,
        'errores': errores,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Importación manual de CDRs / XMLs
# ─────────────────────────────────────────────────────────────────────────────

@comprobantes_bp.route('/importar', methods=['GET'])
@login_required
@requiere_permiso('ventas.ver')
def importar():
    """Página de importación manual de CDRs y XMLs."""
    return render_template('comprobantes/importar.html')


@comprobantes_bp.route('/importar', methods=['POST'])
@login_required
@requiere_permiso('ventas.crear')
def importar_archivos():
    """Procesa los archivos XML/CDR subidos manualmente.

    Acepta múltiples archivos en el campo 'archivos'.
    Retorna JSON con lista de resultados por archivo.
    """
    archivos = request.files.getlist('archivos')
    if not archivos:
        return jsonify({'success': False, 'message': 'No se recibieron archivos.'}), 400

    fs = file_svc.get_file_service()
    resultados = []

    for archivo in archivos:
        filename = secure_filename(archivo.filename or '')
        if not filename.lower().endswith('.xml'):
            resultados.append({
                'filename': archivo.filename,
                'success': False,
                'message': 'Formato no válido. Solo se aceptan archivos .xml',
            })
            continue

        try:
            content = archivo.read()
            info = fs.importar_archivo(filename, content)
            tipo = 'CDR' if info['tipo'] == 'cdr' else 'XML firmado'
            resultados.append({
                'filename': filename,
                'success': True,
                'tipo': info['tipo'],
                'message': f'{tipo} importado correctamente.',
            })
        except Exception as e:
            current_app.logger.error(f'[IMPORT] Error importando {filename}: {e}', exc_info=True)
            resultados.append({
                'filename': filename,
                'success': False,
                'message': f'Error al guardar el archivo: {e}',
            })

    total_ok = sum(1 for r in resultados if r['success'])
    return jsonify({
        'success': True,
        'message': f'{total_ok} de {len(resultados)} archivo(s) importado(s).',
        'resultados': resultados,
    })

"""Rutas de comprobantes: descargas PDF/XML/CDR, reenvío a SUNAT, envío en lote e importación."""
import io
import os
import zipfile
import json
from datetime import datetime
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

    correlativo_8d = str(comp.correlativo).zfill(8)
    nombre_base = f"{comp.serie}-{correlativo_8d}"
    if comp.numero_orden:
        filename = f"{comp.numero_orden}_{nombre_base}.pdf"
    else:
        filename = f"{nombre_base}.pdf"

    if fs.pdf_existe(comp):
        return send_file(
            comp.pdf_path,
            mimetype='application/pdf',
            as_attachment=False,
            download_name=filename,
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
        download_name=filename,
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
# Consultar estado en MiPSE (sin reenviar)
# ─────────────────────────────────────────────────────────────────────────────

@comprobantes_bp.route('/<int:comp_id>/consultar-sunat', methods=['POST'])
@login_required
@requiere_permiso('ventas.ver')
def consultar_sunat(comp_id: int):
    """Consulta el estado actual del comprobante en MiPSE/SUNAT sin reenviarlo."""
    comp = db.session.get(Comprobante, comp_id)
    if not comp:
        abort(404)

    try:
        token = mipse_service.obtener_token()
        nombre = nombre_archivo(comp)
        resultado = mipse_service.consultar_estado(nombre, token)

        estado_sunat = resultado.get('estado_sunat', '')
        tiene_cdr    = bool(resultado.get('cdr'))
        codigo       = resultado.get('codigo', '')
        descripcion  = resultado.get('descripcion', '')

        # Si MiPSE tiene el comprobante como ACEPTADO, actualizar BD y guardar CDR
        if estado_sunat in ('ACEPTADO', 'ACEPTADO CON OBSERVACIONES'):
            comp.estado = 'ACEPTADO'
            comp.codigo_sunat  = str(codigo)
            comp.mensaje_sunat = descripcion
            if not comp.fecha_envio_sunat:
                from datetime import datetime
                comp.fecha_envio_sunat = datetime.utcnow()
            if tiene_cdr:
                fs = file_svc.get_file_service()
                fs.guardar_archivos(comp, resultado)
            db.session.commit()
            message = f'SUNAT tiene el comprobante como ACEPTADO. BD actualizada.'
        elif estado_sunat == 'RECHAZADO':
            comp.estado = 'RECHAZADO'
            comp.codigo_sunat  = str(codigo)
            comp.mensaje_sunat = descripcion
            db.session.commit()
            message = f'SUNAT rechazó el comprobante. Código: {codigo} — {descripcion}'
        else:
            message = f'Estado en MiPSE: {estado_sunat or "desconocido"}. Código: {codigo}. {descripcion}'

        return jsonify({
            'success': True,
            'message': message,
            'estado_sunat': estado_sunat,
            'estado_bd': comp.estado,
            'codigo': codigo,
            'descripcion': descripcion,
            'tiene_cdr': tiene_cdr,
        })

    except mipse_service.MiPSEError as e:
        return jsonify({
            'success': False,
            'message': f'Error consultando MiPSE: {e}',
        }), 502


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
# Descarga masiva (ZIP de PDFs / XMLs / CDRs)
# ─────────────────────────────────────────────────────────────────────────────

@comprobantes_bp.route('/descargar-lote', methods=['POST'])
@login_required
@requiere_permiso('ventas.ver')
def descargar_lote():
    """Genera un ZIP con PDFs, XMLs o CDRs de los comprobantes seleccionados."""
    try:
        payload = request.get_json(force=True) or {}
        ids          = [int(i) for i in payload.get('ids', []) if str(i).isdigit()]
        tipo_archivo = payload.get('tipo', 'pdf').lower()

        if not ids or tipo_archivo not in ('pdf', 'xml', 'cdr'):
            return jsonify({'success': False, 'message': 'Parámetros inválidos.'}), 400

        comprobantes = Comprobante.query.filter(Comprobante.id.in_(ids)).all()
        if not comprobantes:
            return jsonify({'success': False, 'message': 'No se encontraron comprobantes.'}), 404

        fs = file_svc.get_file_service()
        memory_file = io.BytesIO()
        agregados = 0

        with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            for comp in comprobantes:
                correlativo_8d = str(comp.correlativo).zfill(8)
                nombre_base = f"{comp.serie}-{correlativo_8d}"
                prefix = f"{comp.numero_orden}_{nombre_base}" if comp.numero_orden else nombre_base

                if tipo_archivo == 'pdf':
                    if not fs.pdf_existe(comp):
                        try:
                            pdf_bytes = pdf_service.generar_pdf(comp)
                            fs.guardar_pdf(comp, pdf_bytes)
                            db.session.commit()
                        except Exception as e:
                            current_app.logger.warning(f'[BULK-PDF] No se pudo generar PDF de {comp.numero_completo}: {e}')
                            continue
                    try:
                        with open(comp.pdf_path, 'rb') as f:
                            zf.writestr(f'{prefix}.pdf', f.read())
                        agregados += 1
                    except Exception:
                        continue

                elif tipo_archivo == 'xml':
                    if not fs.xml_existe(comp):
                        continue
                    try:
                        with open(comp.xml_path, 'rb') as f:
                            zf.writestr(f'{prefix}.xml', f.read())
                        agregados += 1
                    except Exception:
                        continue

                elif tipo_archivo == 'cdr':
                    if not fs.cdr_existe(comp):
                        continue
                    try:
                        with open(comp.cdr_path, 'rb') as f:
                            zf.writestr(f'R-{prefix}.xml', f.read())
                        agregados += 1
                    except Exception:
                        continue

        if agregados == 0:
            return jsonify({'success': False,
                            'message': f'No se encontraron archivos {tipo_archivo.upper()} para los comprobantes seleccionados.'}), 404

        memory_file.seek(0)
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        zip_name = f'comprobantes_{tipo_archivo}_{timestamp}.zip'

        return send_file(
            memory_file,
            mimetype='application/zip',
            as_attachment=True,
            download_name=zip_name,
        )

    except Exception as e:
        current_app.logger.error(f'[BULK-DOWNLOAD] Error: {e}', exc_info=True)
        return jsonify({'success': False, 'message': f'Error generando ZIP: {e}'}), 500


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

"""Rutas para Notas de Crédito y Notas de Débito."""
from datetime import datetime, date
from decimal import Decimal
from flask import render_template, request, jsonify, abort, current_app
from flask_login import login_required, current_user
from app.extensions import db
from app.models.comprobante import Comprobante, ComprobanteItem
from app.services.utils import calcular_igv_item, calcular_totales_comprobante
from app.services import mipse_service, file_service as file_svc
from app.services.sunat_xml_service import MOTIVOS_NC, MOTIVOS_ND
from app.decorators import requiere_permiso
from . import notas_bp


# ─────────────────────────────────────────────────────────────────────────────
# NC en Lote
# ─────────────────────────────────────────────────────────────────────────────

@notas_bp.route('/nc/lote', methods=['POST'])
@login_required
@requiere_permiso('ventas.crear')
def nc_lote():
    """Emite una Nota de Crédito para un comprobante (llamado uno a uno desde el frontend)."""
    payload       = request.get_json(force=True) or {}
    ids           = [int(i) for i in payload.get('ids', []) if str(i).isdigit()]
    motivo_codigo = payload.get('motivo_codigo', '').strip()

    if not motivo_codigo or motivo_codigo not in MOTIVOS_NC:
        return jsonify({'success': False, 'message': 'Motivo inválido.'}), 400
    if not ids:
        return jsonify({'success': False, 'message': 'Sin comprobantes.'}), 400

    cfg     = current_app.config
    creadas = 0
    errores = []

    for comp_id in ids:
        try:
            comp_ref = db.session.get(Comprobante, comp_id)
            if not comp_ref:
                errores.append({'numero': str(comp_id), 'error': 'No encontrado'}); continue
            if comp_ref.tipo_comprobante not in ('FACTURA', 'BOLETA'):
                errores.append({'numero': comp_ref.numero_completo, 'error': 'No es Factura/Boleta'}); continue
            if comp_ref.estado not in ('ENVIADO', 'ACEPTADO'):
                errores.append({'numero': comp_ref.numero_completo, 'error': f'Estado: {comp_ref.estado}'}); continue
            if comp_ref.notas_credito:
                errores.append({'numero': comp_ref.numero_completo, 'error': 'Ya tiene NC'}); continue

            serie = cfg.get('SERIE_NC_FACTURA', 'FC01') if comp_ref.tipo_comprobante == 'FACTURA' \
                    else cfg.get('SERIE_NC_BOLETA', 'BC01')
            correlativo  = _siguiente_correlativo(serie)
            motivo_texto = MOTIVOS_NC[motivo_codigo]

            costo_envio_ref = Decimal(str(comp_ref.costo_envio or '0'))
            descuento_ref   = Decimal(str(comp_ref.descuento or '0'))
            nc = Comprobante(
                tipo_comprobante='NOTA_CREDITO',
                tipo_documento_sunat='07',
                serie=serie,
                correlativo=str(correlativo),
                numero_completo=f'{serie}-{str(correlativo).zfill(8)}',
                cliente_id=comp_ref.cliente_id,
                vendedor_id=current_user.id,
                numero_orden=comp_ref.numero_orden,
                costo_envio=costo_envio_ref,
                descuento=descuento_ref,
                estado='PENDIENTE',
                fecha_emision=datetime.utcnow(),
                comprobante_referencia_id=comp_ref.id,
                motivo_codigo=motivo_codigo,
                motivo_descripcion=motivo_texto,
            )
            db.session.add(nc)
            db.session.flush()

            items_obj = []
            for it in comp_ref.items:
                item = ComprobanteItem(
                    comprobante_id=nc.id,
                    producto_nombre=it.producto_nombre,
                    producto_sku=it.producto_sku,
                    cantidad=it.cantidad,
                    unidad_medida=it.unidad_medida,
                    precio_unitario_con_igv=it.precio_unitario_con_igv,
                    precio_unitario_sin_igv=it.precio_unitario_sin_igv,
                    igv_unitario=it.igv_unitario,
                    subtotal_sin_igv=it.subtotal_sin_igv,
                    igv_total=it.igv_total,
                    subtotal_con_igv=it.subtotal_con_igv,
                    tipo_afectacion_igv=it.tipo_afectacion_igv,
                    variacion_id=it.variacion_id,
                    atributos_json=it.atributos_json,
                )
                db.session.add(item)
                items_obj.append(item)
            db.session.flush()

            totales = calcular_totales_comprobante(items_obj, costo_envio_ref, descuento_ref)
            nc.subtotal                     = sum(i.subtotal_con_igv for i in items_obj)
            nc.total_operaciones_gravadas   = totales['total_gravadas']
            nc.total_operaciones_exoneradas = totales['total_exoneradas']
            nc.total_operaciones_inafectas  = totales['total_inafectas']
            nc.total_igv                    = totales['total_igv']
            nc.total                        = totales['total']
            db.session.commit()

            resultado = mipse_service.procesar_comprobante(nc)
            if resultado['success']:
                file_svc.get_file_service().guardar_archivos(nc, resultado)
            db.session.commit()
            creadas += 1

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'[NC-LOTE] Error en {comp_id}: {e}', exc_info=True)
            errores.append({'numero': str(comp_id), 'error': str(e)})

    return jsonify({
        'success': True,
        'creadas': creadas,
        'errores': errores,
        'message': f'{creadas} NC(s) emitida(s), {len(errores)} omitida(s).',
    })


# ─────────────────────────────────────────────────────────────────────────────
# Nota de Crédito
# ─────────────────────────────────────────────────────────────────────────────

@notas_bp.route('/nc/nueva', methods=['GET'])
@login_required
@requiere_permiso('ventas.crear')
def nueva_nc():
    comp_ref_id = request.args.get('comp_ref_id', type=int)
    if not comp_ref_id:
        abort(400)

    comp_ref = db.session.get(Comprobante, comp_ref_id)
    if not comp_ref or comp_ref.tipo_comprobante not in ('FACTURA', 'BOLETA'):
        abort(404)
    if comp_ref.estado not in ('ENVIADO', 'ACEPTADO'):
        abort(400)

    return render_template('notas/nueva_nc.html',
        comp_ref=comp_ref,
        motivos=MOTIVOS_NC,
        today=date.today().isoformat(),
    )


@notas_bp.route('/nc/crear', methods=['POST'])
@login_required
@requiere_permiso('ventas.crear')
def crear_nc():
    """Crea y envía a SUNAT una Nota de Crédito."""
    try:
        payload = request.get_json(force=True) or {}
        comp_ref_id   = int(payload.get('comp_ref_id', 0))
        motivo_codigo = payload.get('motivo_codigo', '01').strip()
        motivo_desc   = payload.get('motivo_descripcion', '').strip()
        fecha_str     = payload.get('fecha_emision', '').strip()
        try:
            fecha_emision_nc = datetime.strptime(fecha_str, '%Y-%m-%d') if fecha_str else datetime.utcnow()
        except ValueError:
            fecha_emision_nc = datetime.utcnow()

        comp_ref = db.session.get(Comprobante, comp_ref_id)
        if not comp_ref:
            return jsonify({'success': False, 'message': 'Comprobante no encontrado.'}), 404
        if comp_ref.estado not in ('ENVIADO', 'ACEPTADO'):
            return jsonify({'success': False, 'message': 'El comprobante debe estar ENVIADO o ACEPTADO.'}), 400

        cfg = current_app.config
        serie = cfg.get('SERIE_NC_FACTURA', 'FC01') if comp_ref.tipo_comprobante == 'FACTURA' \
                else cfg.get('SERIE_NC_BOLETA', 'BC01')

        correlativo  = _siguiente_correlativo(serie)
        motivo_texto = motivo_desc or MOTIVOS_NC.get(motivo_codigo, '')

        costo_envio_ref = Decimal(str(comp_ref.costo_envio or '0'))
        descuento_ref   = Decimal(str(comp_ref.descuento or '0'))
        nc = Comprobante(
            tipo_comprobante='NOTA_CREDITO',
            tipo_documento_sunat='07',
            serie=serie,
            correlativo=str(correlativo),
            numero_completo=f'{serie}-{str(correlativo).zfill(8)}',
            cliente_id=comp_ref.cliente_id,
            vendedor_id=current_user.id,
            numero_orden=comp_ref.numero_orden,
            costo_envio=costo_envio_ref,
            descuento=descuento_ref,
            estado='PENDIENTE',
            fecha_emision=fecha_emision_nc,
            comprobante_referencia_id=comp_ref.id,
            motivo_codigo=motivo_codigo,
            motivo_descripcion=motivo_texto,
        )
        db.session.add(nc)
        db.session.flush()

        # Clonar ítems del comprobante original
        items_obj = []
        for it in comp_ref.items:
            item = ComprobanteItem(
                comprobante_id=nc.id,
                producto_nombre=it.producto_nombre,
                producto_sku=it.producto_sku,
                cantidad=it.cantidad,
                unidad_medida=it.unidad_medida,
                precio_unitario_con_igv=it.precio_unitario_con_igv,
                precio_unitario_sin_igv=it.precio_unitario_sin_igv,
                igv_unitario=it.igv_unitario,
                subtotal_sin_igv=it.subtotal_sin_igv,
                igv_total=it.igv_total,
                subtotal_con_igv=it.subtotal_con_igv,
                tipo_afectacion_igv=it.tipo_afectacion_igv,
                variacion_id=it.variacion_id,
                atributos_json=it.atributos_json,
            )
            db.session.add(item)
            items_obj.append(item)

        db.session.flush()

        totales = calcular_totales_comprobante(items_obj, costo_envio_ref, descuento_ref)
        nc.subtotal                     = sum(i.subtotal_con_igv for i in items_obj)
        nc.total_operaciones_gravadas   = totales['total_gravadas']
        nc.total_operaciones_exoneradas = totales['total_exoneradas']
        nc.total_operaciones_inafectas  = totales['total_inafectas']
        nc.total_igv                    = totales['total_igv']
        nc.total                        = totales['total']
        db.session.commit()

        resultado = mipse_service.procesar_comprobante(nc)
        if resultado['success']:
            file_svc.get_file_service().guardar_archivos(nc, resultado)
        db.session.commit()

        sunat_aceptado = nc.estado == 'ACEPTADO'
        if not resultado['success']:
            msg = f'NC {nc.numero_completo} guardada como PENDIENTE. Error SUNAT: {resultado["mensaje_sunat"]}'
        elif sunat_aceptado:
            msg = f'NC {nc.numero_completo} emitida y ACEPTADA por SUNAT.'
        else:
            msg = f'NC {nc.numero_completo} RECHAZADA por SUNAT. {resultado.get("mensaje_sunat", "")}'

        return jsonify({
            'success': True,
            'message': msg,
            'comprobante_id': nc.id,
            'numero': nc.numero_completo,
            'estado': nc.estado,
            'sunat_ok': sunat_aceptado,
            'sunat_mensaje': resultado.get('mensaje_sunat', ''),
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'[NC] Error: {e}', exc_info=True)
        return jsonify({'success': False, 'message': f'Error interno: {str(e)}'}), 500


# ─────────────────────────────────────────────────────────────────────────────
# Nota de Débito
# ─────────────────────────────────────────────────────────────────────────────

@notas_bp.route('/nd/nueva', methods=['GET'])
@login_required
@requiere_permiso('ventas.crear')
def nueva_nd():
    comp_ref_id = request.args.get('comp_ref_id', type=int)
    if not comp_ref_id:
        abort(400)

    comp_ref = db.session.get(Comprobante, comp_ref_id)
    if not comp_ref or comp_ref.tipo_comprobante not in ('FACTURA', 'BOLETA'):
        abort(404)
    if comp_ref.estado not in ('ENVIADO', 'ACEPTADO'):
        abort(400)

    return render_template('notas/nueva_nd.html',
        comp_ref=comp_ref,
        motivos=MOTIVOS_ND,
    )


@notas_bp.route('/nd/crear', methods=['POST'])
@login_required
@requiere_permiso('ventas.crear')
def crear_nd():
    """Crea y envía a SUNAT una Nota de Débito."""
    try:
        payload = request.get_json(force=True) or {}
        comp_ref_id     = int(payload.get('comp_ref_id', 0))
        motivo_codigo   = payload.get('motivo_codigo', '01').strip()
        motivo_desc     = payload.get('motivo_descripcion', '').strip()
        monto_adicional = Decimal(str(payload.get('monto_adicional', '0')))
        descripcion     = payload.get('descripcion', '').strip() or 'Cargo adicional'

        if monto_adicional <= 0:
            return jsonify({'success': False, 'message': 'El monto adicional debe ser mayor a 0.'}), 400

        comp_ref = db.session.get(Comprobante, comp_ref_id)
        if not comp_ref:
            return jsonify({'success': False, 'message': 'Comprobante no encontrado.'}), 404
        if comp_ref.estado not in ('ENVIADO', 'ACEPTADO'):
            return jsonify({'success': False, 'message': 'El comprobante debe estar ENVIADO o ACEPTADO.'}), 400

        cfg   = current_app.config
        serie = cfg.get('SERIE_ND_FACTURA', 'FD01') if comp_ref.tipo_comprobante == 'FACTURA' \
                else cfg.get('SERIE_ND_BOLETA', 'BD01')

        correlativo  = _siguiente_correlativo(serie)
        motivo_texto = motivo_desc or MOTIVOS_ND.get(motivo_codigo, '')

        nd = Comprobante(
            tipo_comprobante='NOTA_DEBITO',
            tipo_documento_sunat='08',
            serie=serie,
            correlativo=str(correlativo),
            numero_completo=f'{serie}-{str(correlativo).zfill(8)}',
            cliente_id=comp_ref.cliente_id,
            vendedor_id=current_user.id,
            numero_orden=comp_ref.numero_orden,
            costo_envio=Decimal('0.00'),
            estado='PENDIENTE',
            fecha_emision=datetime.utcnow(),
            comprobante_referencia_id=comp_ref.id,
            motivo_codigo=motivo_codigo,
            motivo_descripcion=motivo_texto,
        )
        db.session.add(nd)
        db.session.flush()

        calc = calcular_igv_item(monto_adicional, Decimal('1'), '10')
        item = ComprobanteItem(
            comprobante_id=nd.id,
            producto_nombre=descripcion,
            producto_sku='',
            cantidad=Decimal('1'),
            unidad_medida='NIU',
            precio_unitario_con_igv=monto_adicional,
            precio_unitario_sin_igv=calc['precio_sin_igv'],
            igv_unitario=calc['igv_unitario'],
            subtotal_sin_igv=calc['subtotal_sin_igv'],
            igv_total=calc['igv_total'],
            subtotal_con_igv=calc['subtotal_con_igv'],
            tipo_afectacion_igv='10',
        )
        db.session.add(item)
        db.session.flush()

        nd.subtotal                     = item.subtotal_con_igv
        nd.total_operaciones_gravadas   = item.subtotal_sin_igv
        nd.total_operaciones_exoneradas = Decimal('0.00')
        nd.total_operaciones_inafectas  = Decimal('0.00')
        nd.total_igv                    = item.igv_total
        nd.total                        = item.subtotal_con_igv
        db.session.commit()

        resultado = mipse_service.procesar_comprobante(nd)
        if resultado['success']:
            file_svc.get_file_service().guardar_archivos(nd, resultado)
        db.session.commit()

        sunat_aceptado = nd.estado == 'ACEPTADO'
        if not resultado['success']:
            msg = f'ND {nd.numero_completo} guardada como PENDIENTE. Error SUNAT: {resultado["mensaje_sunat"]}'
        elif sunat_aceptado:
            msg = f'ND {nd.numero_completo} emitida y ACEPTADA por SUNAT.'
        else:
            msg = f'ND {nd.numero_completo} RECHAZADA por SUNAT. {resultado.get("mensaje_sunat", "")}'

        return jsonify({
            'success': True,
            'message': msg,
            'comprobante_id': nd.id,
            'numero': nd.numero_completo,
            'estado': nd.estado,
            'sunat_ok': sunat_aceptado,
            'sunat_mensaje': resultado.get('mensaje_sunat', ''),
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'[ND] Error: {e}', exc_info=True)
        return jsonify({'success': False, 'message': f'Error interno: {str(e)}'}), 500


# ─────────────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────────────

def _siguiente_correlativo(serie: str) -> int:
    subq = (
        db.session.query(db.cast(Comprobante.correlativo, db.Integer))
        .filter_by(serie=serie)
        .with_for_update()
        .subquery()
    )
    ultimo = db.session.query(db.func.max(subq.c.correlativo)).scalar()
    return (ultimo or 0) + 1

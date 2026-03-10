"""Rutas de ventas: POS (nueva venta), listado y detalle de comprobantes."""
import json
from datetime import datetime, date
from decimal import Decimal
from flask import render_template, request, jsonify, current_app, abort
from flask_login import login_required, current_user
from sqlalchemy import func
from app.extensions import db
from app.models.comprobante import Comprobante, ComprobanteItem
from app.models.cliente import Cliente
from app.services.cliente_service import (
    buscar_cliente_local,
    guardar_cliente_desde_dict,
)
from app.services.utils import calcular_igv_item, calcular_totales_comprobante
from app.services import mipse_service, file_service as file_svc
from app.decorators import requiere_permiso
from . import ventas_bp


# ─────────────────────────────────────────────────────────────────────────────
# POS — Nueva Venta
# ─────────────────────────────────────────────────────────────────────────────

@ventas_bp.route('/nueva', methods=['GET'])
@login_required
@requiere_permiso('ventas.crear')
def nueva_venta():
    config = current_app.config
    return render_template('ventas/nueva.html',
        serie_factura=config.get('SERIE_FACTURA', 'F001'),
        serie_boleta=config.get('SERIE_BOLETA', 'B001'),
    )


@ventas_bp.route('/nueva', methods=['POST'])
@login_required
@requiere_permiso('ventas.crear')
def crear_venta():
    """Recibe JSON del POS, crea el Comprobante y lo envía a SUNAT."""
    try:
        payload = request.get_json(force=True)
        if not payload:
            return jsonify({'success': False, 'message': 'Datos inválidos.'}), 400

        # ── Validaciones básicas ──
        cliente_datos      = payload.get('cliente')
        items_datos        = payload.get('items', [])
        costo_envio        = Decimal(str(payload.get('costo_envio', '0')))
        descuento          = Decimal(str(payload.get('descuento', '0')))
        numero_orden       = payload.get('numero_orden', '').strip() or None
        fecha_emision_str  = (payload.get('fecha_emision') or '').strip() or None

        if not cliente_datos:
            return jsonify({'success': False, 'message': 'Cliente requerido.'}), 400
        if not items_datos:
            return jsonify({'success': False, 'message': 'Se requiere al menos un ítem.'}), 400

        # ── Guardar / recuperar cliente ──
        cliente = guardar_cliente_desde_dict(cliente_datos)

        # ── Determinar tipo y serie ──
        config = current_app.config
        if cliente.tipo_documento == 'RUC':
            tipo_comp   = 'FACTURA'
            tipo_sunat  = '01'
            serie       = config.get('SERIE_FACTURA', 'F001')
        else:
            tipo_comp   = 'BOLETA'
            tipo_sunat  = '03'
            serie       = config.get('SERIE_BOLETA', 'B001')

        # ── Fecha de emisión ──
        fecha_emision = datetime.utcnow()
        if fecha_emision_str:
            try:
                fecha_emision = datetime.strptime(fecha_emision_str, '%Y-%m-%d')
            except ValueError:
                pass

        # ── Correlativo ──
        correlativo = _siguiente_correlativo(serie)

        # ── Crear comprobante ──
        comprobante = Comprobante(
            tipo_comprobante=tipo_comp,
            tipo_documento_sunat=tipo_sunat,
            serie=serie,
            correlativo=str(correlativo),
            numero_completo=f'{serie}-{str(correlativo).zfill(8)}',
            cliente_id=cliente.id,
            vendedor_id=current_user.id,
            numero_orden=numero_orden,
            costo_envio=costo_envio,
            descuento=descuento,
            estado='PENDIENTE',
            fecha_emision=fecha_emision,
        )
        db.session.add(comprobante)
        db.session.flush()

        # ── Calcular totales bruto para prorrateo de descuento ──
        total_items_bruto = sum(Decimal(str(it['precio_con_igv'])) * Decimal(str(it['cantidad'])) for it in items_datos)
        descuento_restante = descuento

        # ── Crear ítems ──
        items_obj = []
        for index, it in enumerate(items_datos):
            precio_con_igv_original = Decimal(str(it['precio_con_igv']))
            cantidad = Decimal(str(it['cantidad']))
            tipo_afectacion = it.get('tipo_afectacion_igv', '10')

            # ── Prorratear descuento ──
            descuento_item = Decimal('0')
            if descuento > 0 and total_items_bruto > 0:
                if index == len(items_datos) - 1:
                    # Último ítem asume el remanente del descuento por redondeo
                    descuento_item = descuento_restante
                else:
                    porcion = ((precio_con_igv_original * cantidad) / total_items_bruto) * descuento
                    descuento_item = porcion.quantize(Decimal('0.01'))
                    descuento_restante -= descuento_item

            descuento_unitario = (descuento_item / cantidad) if cantidad > 0 else Decimal('0')
            precio_con_igv = precio_con_igv_original - descuento_unitario

            calc = calcular_igv_item(precio_con_igv, cantidad, tipo_afectacion)

            item = ComprobanteItem(
                comprobante_id=comprobante.id,
                producto_nombre=it['nombre'],
                producto_sku=it.get('sku', ''),
                cantidad=cantidad,
                unidad_medida=it.get('unidad_medida', 'NIU'),
                descuento=descuento_item,
                precio_unitario_con_igv=precio_con_igv,
                precio_unitario_sin_igv=calc['precio_sin_igv'],
                igv_unitario=calc['igv_unitario'],
                subtotal_sin_igv=calc['subtotal_sin_igv'],
                igv_total=calc['igv_total'],
                subtotal_con_igv=calc['subtotal_con_igv'],
                tipo_afectacion_igv=tipo_afectacion,
                variacion_id=it.get('variacion_id'),
                atributos_json=it.get('atributos') or None,
            )
            db.session.add(item)
            items_obj.append(item)

        db.session.flush()

        # ── Calcular totales del comprobante ──
        # El descuento ya está aplicado en los precios de los ítems, por lo que a la 
        # función de utilidades le enviamos descuento=0 para que no lo reste 2 veces.
        totales = calcular_totales_comprobante(items_obj, costo_envio, Decimal('0'))
        comprobante.subtotal = sum(i.subtotal_con_igv for i in items_obj)
        comprobante.total_operaciones_gravadas   = totales['total_gravadas']
        comprobante.total_operaciones_exoneradas = totales['total_exoneradas']
        comprobante.total_operaciones_inafectas  = totales['total_inafectas']
        comprobante.total_igv                    = totales['total_igv']
        comprobante.total                        = totales['total']

        db.session.commit()

        # ── Enviar a SUNAT vía MiPSE ──
        resultado_mipse = mipse_service.procesar_comprobante(comprobante)
        if resultado_mipse['success']:
            fs = file_svc.get_file_service()
            fs.guardar_archivos(comprobante, resultado_mipse)

        db.session.commit()

        sunat_aceptado = comprobante.estado == 'ACEPTADO'

        if not resultado_mipse['success']:
            msg = (
                f'Comprobante {comprobante.numero_completo} guardado como PENDIENTE. '
                f'Error SUNAT: {resultado_mipse["mensaje_sunat"]}'
            )
        elif sunat_aceptado:
            msg = f'Comprobante {comprobante.numero_completo} emitido y ACEPTADO por SUNAT.'
        else:
            msg = (
                f'Comprobante {comprobante.numero_completo} RECHAZADO por SUNAT. '
                f'{resultado_mipse.get("mensaje_sunat", "")}'
            )

        return jsonify({
            'success': True,
            'message': msg,
            'comprobante_id': comprobante.id,
            'numero': comprobante.numero_completo,
            'estado': comprobante.estado,
            'sunat_ok': sunat_aceptado,
            'sunat_mensaje': resultado_mipse.get('mensaje_sunat', ''),
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'[VENTA] Error al crear comprobante: {e}', exc_info=True)
        return jsonify({'success': False, 'message': f'Error interno: {str(e)}'}), 500


# ─────────────────────────────────────────────────────────────────────────────
# Listado de comprobantes
# ─────────────────────────────────────────────────────────────────────────────

@ventas_bp.route('/')
@login_required
@requiere_permiso('ventas.ver')
def lista_ventas():
    """Listado con filtros, búsqueda, ordenamiento y paginación."""
    page      = request.args.get('page', 1, type=int)
    tipo      = request.args.get('tipo', '').strip()
    estado    = request.args.get('estado', '').strip()
    q         = request.args.get('q', '').strip()
    fecha_ini = request.args.get('fecha_ini', '').strip()
    fecha_fin = request.args.get('fecha_fin', '').strip()
    sort      = request.args.get('sort', '').strip()
    sort_dir  = request.args.get('dir', 'desc').strip()

    sort_map = {
        'orden':        Comprobante.numero_orden,
        'comprobante':  Comprobante.numero_completo,
        'fecha_pedido': func.coalesce(Comprobante.fecha_pedido, Comprobante.fecha_emision),
        'fecha':        Comprobante.fecha_emision,
        'cliente':      Cliente.razon_social,
        'total':        Comprobante.total,
        'estado':       Comprobante.estado,
    }

    if sort and sort in sort_map:
        col = sort_map[sort]
        order_col = col.desc() if sort_dir == 'desc' else col.asc()
    else:
        sort = ''
        order_col = Comprobante.fecha_emision.desc()

    query = (
        Comprobante.query
        .join(Comprobante.cliente)
        .order_by(order_col)
    )

    if tipo:
        query = query.filter(Comprobante.tipo_comprobante == tipo)
    if estado:
        query = query.filter(Comprobante.estado == estado)
    if q:
        t = f'%{q}%'
        query = query.filter(
            db.or_(
                Comprobante.numero_completo.ilike(t),
                Comprobante.numero_orden.ilike(t),
                Cliente.razon_social.ilike(t),
                Cliente.nombres.ilike(t),
                Cliente.numero_documento.ilike(t),
            )
        )
    if fecha_ini:
        try:
            query = query.filter(
                Comprobante.fecha_emision >= datetime.strptime(fecha_ini, '%Y-%m-%d')
            )
        except ValueError:
            pass
    if fecha_fin:
        try:
            from datetime import timedelta
            query = query.filter(
                Comprobante.fecha_emision < datetime.strptime(fecha_fin, '%Y-%m-%d') + timedelta(days=1)
            )
        except ValueError:
            pass

    comprobantes = query.paginate(page=page, per_page=25, error_out=False)
    filtros = {'tipo': tipo, 'estado': estado, 'q': q,
               'fecha_ini': fecha_ini, 'fecha_fin': fecha_fin}

    return render_template('ventas/lista.html',
        comprobantes=comprobantes,
        filtros=filtros,
        sort=sort,
        sort_dir=sort_dir,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Detalle de comprobante
# ─────────────────────────────────────────────────────────────────────────────

@ventas_bp.route('/<int:comp_id>')
@login_required
@requiere_permiso('ventas.ver')
def detalle_venta(comp_id: int):
    comprobante = db.session.get(Comprobante, comp_id)
    if not comprobante:
        abort(404)
    fs = file_svc.get_file_service()
    return render_template('ventas/detalle.html',
        comprobante=comprobante,
        xml_existe=fs.xml_existe(comprobante),
        cdr_existe=fs.cdr_existe(comprobante),
        pdf_existe=fs.pdf_existe(comprobante),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _siguiente_correlativo(serie: str) -> int:
    """Obtiene el siguiente correlativo para una serie dada (con lock de fila).
    PostgreSQL no permite FOR UPDATE con aggregate functions, por lo que se
    bloquean las filas en un subquery y luego se obtiene el MAX.
    """
    subq = (
        db.session.query(db.cast(Comprobante.correlativo, db.Integer))
        .filter_by(serie=serie)
        .with_for_update()
        .subquery()
    )
    ultimo = db.session.query(db.func.max(subq.c.correlativo)).scalar()
    return (ultimo or 0) + 1

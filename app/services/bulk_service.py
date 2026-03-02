"""Servicio de carga masiva desde Excel de WooCommerce.

Columnas Excel (0-indexed):
  B(1)=SKU | D(3)=Fecha | E(4)=N°Orden | J(9)=Nombre | L(11)=DNI/RUC
  AJ(35)=Precio | AK(36)=Descripción | AL(37)=Costo Envío
"""
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

import pandas as pd

from app.extensions import db
from app.models.cliente import Cliente
from app.models.comprobante import Comprobante, ComprobanteItem
from app.models.producto import Variacion, Producto
from app.services.utils import calcular_igv_item, calcular_totales_comprobante
from app.services import mipse_service, file_service as file_svc
from app.services.cliente_service import buscar_o_crear_cliente

logger = logging.getLogger(__name__)

# Índices de columna (0-based)
_COL_SKU        = 1
_COL_FECHA      = 3
_COL_ORDEN      = 4
_COL_NOMBRE     = 9
_COL_DOC        = 11
_COL_PRECIO     = 35
_COL_DESC       = 36
_COL_ENVIO      = 37

_IGV_FACTOR = Decimal('1.18')


# ─────────────────────────────────────────────────────────────────────────────
# Análisis del Excel
# ─────────────────────────────────────────────────────────────────────────────

def analizar_excel(file_path: str, config: dict) -> list[dict]:
    """
    Lee el Excel y agrupa filas por N° Orden.
    Retorna lista de dicts con status='OK'|'WARNING'|'ERROR'.
    """
    try:
        df = pd.read_excel(file_path, header=0, dtype=str)
    except Exception as exc:
        logger.error('[BULK] Error leyendo Excel: %s', exc)
        raise ValueError(f'No se pudo leer el archivo Excel: {exc}')

    # Agrupar por N° Orden
    ordenes: dict[str, dict] = {}

    for _, row in df.iterrows():
        numero_orden = _val(row, _COL_ORDEN)
        if not numero_orden:
            continue

        if numero_orden not in ordenes:
            ordenes[numero_orden] = {
                'numero_orden': numero_orden,
                'nombre_cliente': _val(row, _COL_NOMBRE),
                'numero_documento': _normalizar_doc(_val(row, _COL_DOC)),
                'fecha_str': _val(row, _COL_FECHA),
                'costo_envio_str': _val(row, _COL_ENVIO) or '0',
                'items_raw': [],
                'errores': [],
                'advertencias': [],
            }

        ordenes[numero_orden]['items_raw'].append({
            'sku':         _val(row, _COL_SKU),
            'descripcion': _val(row, _COL_DESC) or _val(row, _COL_NOMBRE),
            'precio_str':  _val(row, _COL_PRECIO) or '0',
        })

    resultados = []
    for numero_orden, orden in ordenes.items():
        resultado = _analizar_orden(orden, config)
        resultados.append(resultado)

    resultados.sort(key=lambda r: r['numero_orden'])
    return resultados


def _analizar_orden(orden: dict, config: dict) -> dict:
    """Valida una orden y retorna su resumen de análisis."""
    errores = list(orden['errores'])
    advertencias = list(orden['advertencias'])
    items_analizados = []

    # Fecha
    fecha_emision = _parsear_fecha(orden['fecha_str'])

    # Cliente
    numero_doc = orden['numero_documento']
    tipo_comprobante = 'BOLETA'
    serie = config.get('SERIE_BOLETA', 'B001')
    cliente_info = None

    if not numero_doc:
        errores.append('Sin número de documento.')
    else:
        resultado_cli = buscar_o_crear_cliente(numero_doc)
        if resultado_cli['encontrado']:
            cli = resultado_cli['cliente']
            cliente_info = cli
            if cli['tipo_documento'] == 'RUC':
                tipo_comprobante = 'FACTURA'
                serie = config.get('SERIE_FACTURA', 'F001')
        else:
            advertencias.append(f'Documento {numero_doc} no encontrado; se usará como consumidor final.')

    # Costo de envío
    try:
        costo_envio = Decimal(str(orden['costo_envio_str']).replace(',', '.').strip() or '0')
    except InvalidOperation:
        costo_envio = Decimal('0')

    # Ítems
    for item_raw in orden['items_raw']:
        item_analizado = _analizar_item(item_raw)
        items_analizados.append(item_analizado)
        if item_analizado['error']:
            errores.append(item_analizado['error'])

    # Verificar duplicado
    ya_existe = Comprobante.query.filter_by(
        numero_orden=orden['numero_orden']
    ).first() is not None
    if ya_existe:
        errores.append(f'Orden {orden["numero_orden"]} ya tiene comprobante.')

    # Totales provisionales
    total = sum(
        Decimal(str(it.get('subtotal_con_igv', 0)))
        for it in items_analizados
        if not it.get('error')
    ) + costo_envio

    status = 'ERROR' if errores else ('WARNING' if advertencias else 'OK')

    return {
        'numero_orden':    orden['numero_orden'],
        'fecha_emision':   fecha_emision.isoformat() if fecha_emision else None,
        'nombre_cliente':  orden['nombre_cliente'],
        'numero_documento': numero_doc,
        'cliente_info':    cliente_info,
        'tipo_comprobante': tipo_comprobante,
        'serie':           serie,
        'costo_envio':     str(costo_envio),
        'items':           items_analizados,
        'total_estimado':  str(total),
        'errores':         errores,
        'advertencias':    advertencias,
        'status':          status,
        'ya_existe':       ya_existe,
    }


def _analizar_item(item_raw: dict) -> dict:
    """Analiza un ítem individual: busca variación/producto, calcula IGV."""
    sku   = (item_raw.get('sku') or '').strip()
    desc  = (item_raw.get('descripcion') or sku or 'Producto').strip()
    error = None

    try:
        precio_con_igv = Decimal(
            str(item_raw.get('precio_str', '0')).replace(',', '.').strip() or '0'
        )
    except InvalidOperation:
        precio_con_igv = Decimal('0')

    if precio_con_igv <= 0:
        error = f'Precio inválido para SKU "{sku}".'

    # Buscar variación o producto
    variacion_id = None
    if sku:
        var = Variacion.query.filter(Variacion.sku.ilike(sku)).first()
        if var:
            variacion_id = var.id
            desc = desc or f'{var.producto.nombre} - {sku}'
        else:
            prod = Producto.query.filter(Producto.sku.ilike(sku)).first()
            if not prod:
                error = error or f'SKU "{sku}" no encontrado en la BD.'

    calc = calcular_igv_item(precio_con_igv, Decimal('1'), '10')

    return {
        'sku':                    sku,
        'descripcion':            desc,
        'precio_con_igv':         str(precio_con_igv),
        'precio_sin_igv':         str(calc['precio_sin_igv']),
        'igv_unitario':           str(calc['igv_unitario']),
        'subtotal_sin_igv':       str(calc['subtotal_sin_igv']),
        'igv_total':              str(calc['igv_total']),
        'subtotal_con_igv':       str(calc['subtotal_con_igv']),
        'variacion_id':           variacion_id,
        'error':                  error,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Procesamiento (crear comprobantes)
# ─────────────────────────────────────────────────────────────────────────────

def procesar_ordenes(
    ordenes_json: list[dict],
    config: dict,
    vendedor_id: int,
    fecha_override: Optional[str] = None,
) -> list[dict]:
    """
    Crea comprobantes para las órdenes OK o WARNING seleccionadas.
    Si fecha_override (YYYY-MM-DD) está definida, sobreescribe la fecha de todas las órdenes.
    Retorna lista de resultados por orden.
    """
    resultados = []

    for orden in ordenes_json:
        if orden.get('status') == 'ERROR' or orden.get('ya_existe'):
            resultados.append({
                'numero_orden': orden['numero_orden'],
                'success': False,
                'message': 'Omitida (ERROR o ya existe).',
            })
            continue

        try:
            resultado = _crear_comprobante(orden, config, vendedor_id, fecha_override=fecha_override)
            resultados.append(resultado)
        except Exception as exc:
            db.session.rollback()
            logger.error('[BULK] Error procesando orden %s: %s', orden['numero_orden'], exc, exc_info=True)
            resultados.append({
                'numero_orden': orden['numero_orden'],
                'success': False,
                'message': f'Error interno: {exc}',
            })

    return resultados


def _siguiente_correlativo(serie: str) -> int:
    """Retorna el siguiente número correlativo para una serie."""
    ultimo = (
        db.session.query(db.func.max(db.cast(Comprobante.correlativo, db.Integer)))
        .filter(Comprobante.serie == serie)
        .scalar()
    )
    return (ultimo or 0) + 1


def _crear_comprobante(
    orden: dict,
    config: dict,
    vendedor_id: int,
    fecha_override: Optional[str] = None,
) -> dict:
    """Crea y envía a SUNAT un comprobante para una orden analizada."""
    tipo_comprobante = orden['tipo_comprobante']
    serie = orden['serie']
    numero_doc = orden.get('numero_documento', '')

    # Resolver cliente
    cliente_id = None
    if numero_doc:
        resultado_cli = buscar_o_crear_cliente(numero_doc)
        if resultado_cli['encontrado']:
            from app.models.cliente import Cliente as ClienteModel
            cli = ClienteModel.query.filter_by(
                numero_documento=numero_doc
            ).first()
            if cli:
                cliente_id = cli.id

    if not cliente_id and tipo_comprobante == 'FACTURA':
        raise ValueError(f'No se encontró cliente RUC {numero_doc} para emitir factura.')

    # Fecha de emisión: fecha_override tiene prioridad sobre la del Excel
    fecha_emision = None
    if fecha_override:
        try:
            fecha_emision = datetime.strptime(fecha_override, '%Y-%m-%d')
        except (ValueError, TypeError):
            pass
    if not fecha_emision and orden.get('fecha_emision'):
        try:
            fecha_emision = datetime.fromisoformat(orden['fecha_emision'])
        except (ValueError, TypeError):
            pass
    fecha_emision = fecha_emision or datetime.utcnow()

    tipo_doc_sunat = '01' if tipo_comprobante == 'FACTURA' else '03'
    correlativo = _siguiente_correlativo(serie)
    costo_envio = Decimal(str(orden.get('costo_envio', '0')))

    comp = Comprobante(
        tipo_comprobante=tipo_comprobante,
        tipo_documento_sunat=tipo_doc_sunat,
        serie=serie,
        correlativo=str(correlativo),
        numero_completo=f'{serie}-{str(correlativo).zfill(8)}',
        cliente_id=cliente_id,
        vendedor_id=vendedor_id,
        numero_orden=orden['numero_orden'],
        costo_envio=costo_envio,
        estado='PENDIENTE',
        fecha_emision=fecha_emision,
    )
    db.session.add(comp)
    db.session.flush()

    # Crear ítems
    items_obj = []
    for it in orden.get('items', []):
        if it.get('error'):
            continue
        item = ComprobanteItem(
            comprobante_id=comp.id,
            producto_nombre=it['descripcion'],
            producto_sku=it.get('sku', ''),
            cantidad=Decimal('1'),
            unidad_medida='NIU',
            precio_unitario_con_igv=Decimal(it['precio_con_igv']),
            precio_unitario_sin_igv=Decimal(it['precio_sin_igv']),
            igv_unitario=Decimal(it['igv_unitario']),
            subtotal_sin_igv=Decimal(it['subtotal_sin_igv']),
            igv_total=Decimal(it['igv_total']),
            subtotal_con_igv=Decimal(it['subtotal_con_igv']),
            tipo_afectacion_igv='10',
            variacion_id=it.get('variacion_id'),
        )
        db.session.add(item)
        items_obj.append(item)

    db.session.flush()

    totales = calcular_totales_comprobante(items_obj, costo_envio)
    comp.subtotal                     = sum(i.subtotal_con_igv for i in items_obj)
    comp.total_operaciones_gravadas   = totales['total_gravadas']
    comp.total_operaciones_exoneradas = totales['total_exoneradas']
    comp.total_operaciones_inafectas  = totales['total_inafectas']
    comp.total_igv                    = totales['total_igv']
    comp.total                        = totales['total']
    db.session.commit()

    # Enviar a SUNAT
    resultado_mipse = mipse_service.procesar_comprobante(comp)
    if resultado_mipse['success']:
        file_svc.get_file_service().guardar_archivos(comp, resultado_mipse)
    db.session.commit()

    return {
        'numero_orden':   orden['numero_orden'],
        'success':        True,
        'comprobante_id': comp.id,
        'numero':         comp.numero_completo,
        'estado':         comp.estado,
        'message':        f'{comp.numero_completo} creado. Estado: {comp.estado}.',
    }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _val(row, col_idx: int) -> str:
    """Extrae y limpia un valor de una fila de DataFrame."""
    try:
        v = row.iloc[col_idx]
        return str(v).strip() if pd.notna(v) and str(v).strip() not in ('', 'nan', 'None') else ''
    except (IndexError, KeyError):
        return ''


def _normalizar_doc(doc: str) -> str:
    """Elimina puntos, guiones y espacios del número de documento."""
    if not doc:
        return ''
    return doc.replace('.', '').replace('-', '').replace(' ', '').strip()


def _parsear_fecha(fecha_str: str) -> Optional[datetime]:
    """Intenta parsear fecha en varios formatos comunes."""
    if not fecha_str:
        return None
    formatos = ['%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%Y/%m/%d', '%d/%m/%Y %H:%M:%S']
    for fmt in formatos:
        try:
            return datetime.strptime(fecha_str[:len(fmt)], fmt)
        except (ValueError, TypeError):
            continue
    return None

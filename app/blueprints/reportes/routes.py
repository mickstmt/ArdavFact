"""Rutas de reportes: ganancias con desglose IGV y exportación Excel."""
import io
from datetime import datetime, date
from decimal import Decimal

from flask import render_template, request, send_file, current_app
from flask_login import login_required
from sqlalchemy import func

from app.extensions import db
from app.models.comprobante import Comprobante
from app.models.producto import CostoProducto
from app.decorators import requiere_permiso
from app.services.utils import extraer_skus_base
from . import reportes_bp

_TIPO_CAMBIO = 3.75  # USD → PEN


def _build_mapa_costos() -> dict:
    """Carga todos los costos en memoria: {sku_str: costo_usd}."""
    mapa = {}
    for c in CostoProducto.query.all():
        sku_str = str(c.sku).split('.')[0].strip()
        if sku_str:
            mapa[sku_str] = float(c.costo)
    return mapa

_TIPOS_VENTA   = ('FACTURA', 'BOLETA')
_ESTADOS_VALIDOS = ('ENVIADO', 'ACEPTADO')


# ─────────────────────────────────────────────────────────────────────────────
# Reporte de Ganancias
# ─────────────────────────────────────────────────────────────────────────────

@reportes_bp.route('/ganancias')
@login_required
@requiere_permiso('reportes.ver')
def ganancias():
    """Dashboard financiero con desglose IGV y tabla por comprobante."""
    fecha_ini_str = request.args.get('fecha_ini', '')
    fecha_fin_str = request.args.get('fecha_fin', '')
    tipo_filtro   = request.args.get('tipo', '')
    page          = request.args.get('page', 1, type=int)

    fecha_ini = _parse_date(fecha_ini_str)
    fecha_fin = _parse_date(fecha_fin_str)

    hoy = date.today()
    if not fecha_ini:
        fecha_ini = hoy.replace(day=1)
    if not fecha_fin:
        fecha_fin = hoy

    query = (
        Comprobante.query
        .filter(
            Comprobante.tipo_comprobante.in_(_TIPOS_VENTA),
            Comprobante.estado.in_(_ESTADOS_VALIDOS),
            func.date(Comprobante.fecha_emision) >= fecha_ini,
            func.date(Comprobante.fecha_emision) <= fecha_fin,
        )
    )
    if tipo_filtro in _TIPOS_VENTA:
        query = query.filter(Comprobante.tipo_comprobante == tipo_filtro)

    mapa_costos = _build_mapa_costos()
    todos     = query.all()
    resumen   = _calcular_resumen(todos, mapa_costos)
    paginated = query.order_by(Comprobante.fecha_emision.desc()).paginate(
        page=page, per_page=30, error_out=False
    )
    filas = [_enriquecer_fila(c, mapa_costos) for c in paginated.items]

    return render_template(
        'reportes/ganancias.html',
        resumen=resumen,
        filas=filas,
        comprobantes=paginated,
        fecha_ini=fecha_ini.isoformat(),
        fecha_fin=fecha_fin.isoformat(),
        tipo_filtro=tipo_filtro,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Exportación Excel
# ─────────────────────────────────────────────────────────────────────────────

@reportes_bp.route('/ganancias/exportar')
@login_required
@requiere_permiso('reportes.exportar')
def exportar_ganancias():
    """Exporta reporte a Excel (.xlsx) con hoja de detalle + resumen fiscal."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    fecha_ini = _parse_date(request.args.get('fecha_ini', '')) or date.today().replace(day=1)
    fecha_fin = _parse_date(request.args.get('fecha_fin', '')) or date.today()
    tipo_filtro = request.args.get('tipo', '')

    query = (
        Comprobante.query
        .filter(
            Comprobante.tipo_comprobante.in_(_TIPOS_VENTA),
            Comprobante.estado.in_(_ESTADOS_VALIDOS),
            func.date(Comprobante.fecha_emision) >= fecha_ini,
            func.date(Comprobante.fecha_emision) <= fecha_fin,
        )
        .order_by(Comprobante.fecha_emision)
    )
    if tipo_filtro in _TIPOS_VENTA:
        query = query.filter(Comprobante.tipo_comprobante == tipo_filtro)

    mapa_costos = _build_mapa_costos()
    todos   = query.all()
    resumen = _calcular_resumen(todos, mapa_costos)
    filas   = [_enriquecer_fila(c, mapa_costos) for c in todos]

    wb = openpyxl.Workbook()

    # ── Hoja 1: Detalle ──────────────────────────────────────────────────────
    ws = wb.active
    ws.title = 'Detalle'
    _COLOR_HDR = 'FF1e3a5f'

    hdrs = [
        'N° Comprobante', 'Tipo', 'Fecha', 'Cliente', 'Estado',
        'Base Imponible', 'IGV 18%', 'Costo Envío', 'Total Ingreso',
        'Costo Productos', 'Ganancia Bruta', 'Margen %',
    ]
    ws.append(hdrs)
    for col_idx in range(1, len(hdrs) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.font      = Font(bold=True, color='FFFFFFFF')
        cell.fill      = PatternFill('solid', fgColor=_COLOR_HDR)
        cell.alignment = Alignment(horizontal='center')

    for f in filas:
        ws.append([
            f['numero_completo'],
            f['tipo_comprobante'],
            f['fecha_emision'],
            f['cliente_nombre'],
            f['estado'],
            float(f['base_imponible']),
            float(f['total_igv']),
            float(f['costo_envio']),
            float(f['total']),
            float(f['costo_productos']),
            float(f['ganancia_bruta']),
            float(f['margen_pct']),
        ])

    moneda_cols = {6, 7, 8, 9, 10, 11}
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        for cell in row:
            if cell.column in moneda_cols:
                cell.number_format = '"S/ "#,##0.00'
            elif cell.column == 12:
                cell.number_format = '0.00"%"'

    for col in ws.columns:
        ws.column_dimensions[get_column_letter(col[0].column)].width = min(
            max((len(str(c.value)) for c in col if c.value), default=10) + 4, 40
        )

    # ── Hoja 2: Resumen Fiscal ───────────────────────────────────────────────
    ws2 = wb.create_sheet('Resumen Fiscal')
    cfg  = current_app.config
    ws2.append(['RESUMEN FISCAL'])
    ws2['A1'].font = Font(bold=True, size=14)
    ws2.append([f'{cfg.get("EMPRESA_RAZON_SOCIAL","")} — RUC {cfg.get("EMPRESA_RUC","")}'])
    ws2.append([f'Período: {fecha_ini.strftime("%d/%m/%Y")} — {fecha_fin.strftime("%d/%m/%Y")}'])
    ws2.append([])
    ws2.append(['Concepto', 'Monto (S/)'])
    ws2['A5'].font = ws2['B5'].font = Font(bold=True)

    for concepto, monto in [
        ('Total Ingresos (con IGV)',  resumen['total_ingresos']),
        ('Base Imponible (sin IGV)',  resumen['base_imponible']),
        ('IGV 18% Cobrado',          resumen['total_igv']),
        ('Costo Envíos',             resumen['gasto_envio']),
        ('Costo Productos',          resumen['costo_productos']),
        ('Ganancia Bruta',           resumen['ganancia_bruta']),
    ]:
        ws2.append([concepto, float(monto)])
        ws2.cell(ws2.max_row, 2).number_format = '"S/ "#,##0.00'

    ws2.append([])
    ws2.append([f'Comprobantes procesados: {resumen["total_comprobantes"]}'])
    ws2.column_dimensions['A'].width = 35
    ws2.column_dimensions['B'].width = 18

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    nombre = f'ganancias_consolidado_{fecha_ini.strftime("%Y%m%d")}_{fecha_fin.strftime("%Y%m%d")}.xlsx'
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=nombre,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Exportación Excel — Detallado (por ítem)
# ─────────────────────────────────────────────────────────────────────────────

@reportes_bp.route('/ganancias/exportar-detallado')
@login_required
@requiere_permiso('reportes.exportar')
def exportar_ganancias_detallado():
    """Exporta reporte detallado a Excel (.xlsx) con una fila por ítem de comprobante."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    fecha_ini   = _parse_date(request.args.get('fecha_ini', '')) or date.today().replace(day=1)
    fecha_fin   = _parse_date(request.args.get('fecha_fin', '')) or date.today()
    tipo_filtro = request.args.get('tipo', '')

    _TIPOS_DETALLADO = _TIPOS_VENTA + ('NOTA_CREDITO',)
    query = (
        Comprobante.query
        .filter(
            Comprobante.tipo_comprobante.in_(_TIPOS_DETALLADO),
            Comprobante.estado.in_(_ESTADOS_VALIDOS),
            func.date(Comprobante.fecha_emision) >= fecha_ini,
            func.date(Comprobante.fecha_emision) <= fecha_fin,
        )
        .order_by(Comprobante.fecha_emision)
    )
    if tipo_filtro in _TIPOS_VENTA:
        query = query.filter(Comprobante.tipo_comprobante == tipo_filtro)

    mapa_costos = _build_mapa_costos()
    comprobantes = query.all()

    _COLOR_HDR = 'FF1e3a5f'
    _COLOR_TOT = 'FFE8F4FD'
    _COLOR_ALT = 'FFF7FAFD'
    BORDER_SIDE = Side(style='thin', color='BDD7EE')
    CELL_BORDER = Border(left=BORDER_SIDE, right=BORDER_SIDE,
                         top=BORDER_SIDE, bottom=BORDER_SIDE)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Detallado'

    hdrs = [
        'N° Comprobante', 'Tipo', 'Fecha', 'Cliente',
        'SKU', 'Producto', 'Cantidad', 'Precio Unit. (S/)',
        'Ingreso Item (S/)', 'Costo Unit. USD', 'Costo Unit. (S/)',
        'Costo Total (S/)', 'Ganancia (S/)', 'Margen %',
    ]
    ws.append(hdrs)
    ws.row_dimensions[1].height = 26
    for col_idx in range(1, len(hdrs) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.font      = Font(bold=True, color='FFFFFFFF', size=11)
        cell.fill      = PatternFill('solid', fgColor=_COLOR_HDR)
        cell.alignment = Alignment(horizontal='center', vertical='center')
        cell.border    = CELL_BORDER

    fmt_soles = '"S/ "#,##0.00'
    fmt_usd   = '"$"#,##0.0000'
    fmt_pct   = '0.00"%"'

    total_ingreso = total_costo = total_ganancia = 0.0
    n_filas = 0

    for comp in comprobantes:
        fecha_str    = comp.fecha_emision.strftime('%d/%m/%Y') if comp.fecha_emision else ''
        cliente_nom  = comp.cliente.nombre_completo if comp.cliente else '—'

        es_nc = comp.tipo_comprobante == 'NOTA_CREDITO'
        for item in comp.items:
            sku = (item.producto_sku or '').strip()
            if not sku or sku == 'ENVIO':
                continue

            cantidad = float(item.cantidad or 1)
            if es_nc:
                ingreso_item   = -float(item.subtotal_con_igv or 0)
                costo_unit_usd = 0.0
                costo_unit_pen = 0.0
                costo_total    = 0.0
            else:
                skus = extraer_skus_base(sku)
                costo_unit_usd = sum(mapa_costos.get(s, 0.0) for s in skus)
                costo_unit_pen = round(costo_unit_usd * _TIPO_CAMBIO, 2)
                costo_total    = round(costo_unit_pen * cantidad, 2)
                ingreso_item   = float(item.subtotal_con_igv or 0)
            ganancia = round(ingreso_item - costo_total, 2)
            margen   = round(ganancia / ingreso_item * 100, 2) if ingreso_item else 0.0

            row_idx = ws.max_row + 1
            ws.append([
                comp.numero_completo,
                comp.tipo_comprobante,
                fecha_str,
                cliente_nom,
                sku,
                item.producto_nombre,
                cantidad,
                float(item.precio_unitario_con_igv or 0),
                ingreso_item,
                round(costo_unit_usd, 4),
                costo_unit_pen,
                costo_total,
                ganancia,
                margen,
            ])
            ws.row_dimensions[row_idx].height = 17
            is_alt = (n_filas % 2 == 0)
            for col_idx, cell in enumerate(ws[row_idx], start=1):
                cell.border = CELL_BORDER
                if is_alt:
                    cell.fill = PatternFill('solid', fgColor=_COLOR_ALT)
                if col_idx in (1, 2, 3, 7):
                    cell.alignment = Alignment(horizontal='center', vertical='center')
                elif col_idx in (5, 6):
                    cell.alignment = Alignment(horizontal='left', vertical='center')
                elif col_idx == 8:
                    cell.alignment     = Alignment(horizontal='right', vertical='center')
                    cell.number_format = fmt_soles
                elif col_idx == 9:
                    cell.alignment     = Alignment(horizontal='right', vertical='center')
                    cell.number_format = fmt_soles
                elif col_idx == 10:
                    cell.alignment     = Alignment(horizontal='right', vertical='center')
                    cell.number_format = fmt_usd
                elif col_idx in (11, 12, 13):
                    cell.alignment     = Alignment(horizontal='right', vertical='center')
                    cell.number_format = fmt_soles
                elif col_idx == 14:
                    cell.alignment     = Alignment(horizontal='right', vertical='center')
                    cell.number_format = fmt_pct

            total_ingreso  += ingreso_item
            total_costo    += costo_total
            total_ganancia += ganancia
            n_filas += 1

    # Fila de totales
    total_row = ws.max_row + 1
    ws.row_dimensions[total_row].height = 22
    totales = ['TOTAL', '', f'{n_filas} ítems', '', '', '', '', '',
               round(total_ingreso, 2), '', '', round(total_costo, 2),
               round(total_ganancia, 2),
               round(total_ganancia / total_ingreso * 100, 2) if total_ingreso else 0]
    ws.append(totales)
    for col_idx, cell in enumerate(ws[total_row], start=1):
        cell.font   = Font(bold=True, size=11)
        cell.fill   = PatternFill('solid', fgColor=_COLOR_TOT)
        cell.border = CELL_BORDER
        cell.alignment = Alignment(horizontal='center' if col_idx <= 3 else 'right',
                                   vertical='center')
        if col_idx in (9, 12, 13):
            cell.number_format = fmt_soles
        elif col_idx == 14:
            cell.number_format = fmt_pct

    # Anchos de columna
    col_widths = [18, 10, 12, 24, 16, 34, 10, 16, 16, 14, 14, 14, 14, 12]
    for i, w in enumerate(col_widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    ws.freeze_panes = 'A2'

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    nombre = f'ganancias_detallado_{fecha_ini.strftime("%Y%m%d")}_{fecha_fin.strftime("%Y%m%d")}.xlsx'
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=nombre,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _calcular_resumen(comprobantes: list, mapa_costos: dict) -> dict:
    total_ingresos  = Decimal('0')
    total_igv       = Decimal('0')
    base_imponible  = Decimal('0')
    gasto_envio     = Decimal('0')
    costo_productos = Decimal('0')

    for c in comprobantes:
        total_ingresos  += c.total or Decimal('0')
        total_igv       += c.total_igv or Decimal('0')
        base_imponible  += c.total_operaciones_gravadas or Decimal('0')
        gasto_envio     += c.costo_envio or Decimal('0')
        costo_productos += _costo_comprobante(c, mapa_costos)

    ganancia_bruta = total_ingresos - costo_productos - gasto_envio

    return {
        'total_ingresos':    total_ingresos,
        'total_igv':         total_igv,
        'base_imponible':    base_imponible,
        'gasto_envio':       gasto_envio,
        'costo_productos':   costo_productos,
        'ganancia_bruta':    ganancia_bruta,
        'total_comprobantes': len(comprobantes),
        'margen_pct': (
            round(float(ganancia_bruta / total_ingresos * 100), 1)
            if total_ingresos > 0 else 0
        ),
    }


def _costo_comprobante(comp: Comprobante, mapa_costos: dict) -> Decimal:
    total = Decimal('0')
    for item in comp.items:
        sku = (item.producto_sku or '').strip()
        if not sku or sku == 'ENVIO':
            continue
        skus = extraer_skus_base(sku)
        costo_unit_usd = sum(mapa_costos.get(s, 0.0) for s in skus)
        costo_unit_pen = Decimal(str(round(costo_unit_usd * _TIPO_CAMBIO, 4)))
        total += costo_unit_pen * (item.cantidad or Decimal('1'))
    return total


def _enriquecer_fila(comp: Comprobante, mapa_costos: dict) -> dict:
    costo_prods   = _costo_comprobante(comp, mapa_costos)
    total         = comp.total or Decimal('0')
    costo_envio   = comp.costo_envio or Decimal('0')
    ganancia      = total - costo_prods - costo_envio
    margen_pct    = round(float(ganancia / total * 100), 1) if total > 0 else 0

    return {
        'id':              comp.id,
        'numero_completo': comp.numero_completo,
        'tipo_comprobante': comp.tipo_comprobante,
        'fecha_emision':   comp.fecha_emision.strftime('%d/%m/%Y') if comp.fecha_emision else '',
        'cliente_nombre':  comp.cliente.nombre_completo if comp.cliente else '—',
        'estado':          comp.estado,
        'base_imponible':  comp.total_operaciones_gravadas or Decimal('0'),
        'total_igv':       comp.total_igv or Decimal('0'),
        'costo_envio':     costo_envio,
        'total':           total,
        'costo_productos': costo_prods,
        'ganancia_bruta':  ganancia,
        'margen_pct':      margen_pct,
    }


def _parse_date(s: str):
    if not s:
        return None
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y'):
        try:
            return datetime.strptime(s, fmt).date()
        except (ValueError, TypeError):
            continue
    return None

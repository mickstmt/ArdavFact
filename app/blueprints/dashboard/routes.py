"""Rutas del dashboard principal."""
from datetime import datetime, date
from decimal import Decimal
from flask import render_template, request
from flask_login import login_required, current_user
from sqlalchemy import func, extract
from app.extensions import db
from app.models.comprobante import Comprobante
from . import dashboard_bp


@dashboard_bp.route('/')
@login_required
def index():
    hoy = date.today()
    try:
        mes  = int(request.args.get('mes',  hoy.month))
        anio = int(request.args.get('anio', hoy.year))
        if not (1 <= mes <= 12):
            mes = hoy.month
        if anio < 2000:
            anio = hoy.year
    except (ValueError, TypeError):
        mes, anio = hoy.month, hoy.year

    es_mes_actual = (mes == hoy.month and anio == hoy.year)

    # Navegación prev/next
    if mes == 1:
        mes_prev, anio_prev = 12, anio - 1
    else:
        mes_prev, anio_prev = mes - 1, anio
    if mes == 12:
        mes_next, anio_next = 1, anio + 1
    else:
        mes_next, anio_next = mes + 1, anio

    # Estados activos (excluye borradores y rechazados para conteo de emisión)
    estados_activos = ['PENDIENTE', 'ENVIADO', 'ACEPTADO']

    # ── Indicadores del mes ──
    facturas_mes = Comprobante.query.filter(
        Comprobante.tipo_comprobante == 'FACTURA',
        Comprobante.estado.in_(estados_activos),
        extract('month', Comprobante.fecha_emision) == mes,
        extract('year',  Comprobante.fecha_emision) == anio,
    ).count()

    boletas_mes = Comprobante.query.filter(
        Comprobante.tipo_comprobante == 'BOLETA',
        Comprobante.estado.in_(estados_activos),
        extract('month', Comprobante.fecha_emision) == mes,
        extract('year',  Comprobante.fecha_emision) == anio,
    ).count()

    nc_mes = Comprobante.query.filter(
        Comprobante.tipo_comprobante == 'NOTA_CREDITO',
        Comprobante.estado.in_(estados_activos),
        extract('month', Comprobante.fecha_emision) == mes,
        extract('year',  Comprobante.fecha_emision) == anio,
    ).count()

    pendientes = Comprobante.query.filter_by(estado='PENDIENTE').count()
    rechazados = Comprobante.query.filter_by(estado='RECHAZADO').count()

    # ── Totales del mes ──
    totales_mes = db.session.query(
        func.coalesce(func.sum(Comprobante.total), 0).label('facturacion'),
        func.coalesce(func.sum(Comprobante.total_igv), 0).label('igv'),
    ).filter(
        Comprobante.tipo_comprobante.in_(['FACTURA', 'BOLETA']),
        Comprobante.estado.in_(estados_activos),
        extract('month', Comprobante.fecha_emision) == mes,
        extract('year',  Comprobante.fecha_emision) == anio,
    ).one()

    facturacion_mes = Decimal(str(totales_mes.facturacion))
    igv_mes = Decimal(str(totales_mes.igv))

    # ── Total bulk del mes ──
    total_bulk_mes = db.session.query(
        func.coalesce(func.sum(Comprobante.total), 0)
    ).filter(
        Comprobante.es_bulk == True,
        Comprobante.tipo_comprobante.in_(['FACTURA', 'BOLETA']),
        Comprobante.estado.in_(estados_activos),
        extract('month', Comprobante.fecha_emision) == mes,
        extract('year',  Comprobante.fecha_emision) == anio,
    ).scalar()
    total_bulk_mes = Decimal(str(total_bulk_mes))

    # ── Gráfico semanal (últimas 8 semanas, agrupado por semana del año) ──
    semanas = db.session.query(
        extract('week', Comprobante.fecha_emision).label('semana'),
        func.coalesce(func.sum(Comprobante.total), 0).label('total'),
    ).filter(
        Comprobante.tipo_comprobante.in_(['FACTURA', 'BOLETA']),
        Comprobante.estado.in_(estados_activos),
        extract('year', Comprobante.fecha_emision) == anio,
        extract('week', Comprobante.fecha_emision) >= extract('week', func.now()) - 7,
    ).group_by('semana').order_by('semana').all()

    grafico_labels = [f'Sem {int(s.semana)}' for s in semanas]
    grafico_data   = [float(s.total) for s in semanas]

    # ── Últimos 10 comprobantes ──
    ultimos = (
        Comprobante.query
        .order_by(Comprobante.fecha_emision.desc())
        .limit(10)
        .all()
    )

    mes_nombre = date(anio, mes, 1).strftime('%B %Y')

    return render_template('dashboard/index.html',
        total_bulk_mes=total_bulk_mes,
        facturas_mes=facturas_mes,
        boletas_mes=boletas_mes,
        nc_mes=nc_mes,
        pendientes=pendientes,
        rechazados=rechazados,
        facturacion_mes=facturacion_mes,
        igv_mes=igv_mes,
        grafico_labels=grafico_labels,
        grafico_data=grafico_data,
        ultimos=ultimos,
        mes_nombre=mes_nombre,
        es_mes_actual=es_mes_actual,
        mes_prev=mes_prev, anio_prev=anio_prev,
        mes_next=mes_next, anio_next=anio_next,
    )

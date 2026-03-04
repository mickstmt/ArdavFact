"""Generación de PDF para comprobantes electrónicos con ReportLab.

Soporta: Factura, Boleta, Nota de Crédito, Nota de Débito.
Incluye desglose IGV 18% y código QR SUNAT.
"""
import io
import qrcode
from decimal import Decimal
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Table, TableStyle,
    Spacer, HRFlowable, Image,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from flask import current_app
from app.services.utils import number_to_words_es


# ─────────────────────────────────────────────────────────────────────────────
# Constantes de diseño
# ─────────────────────────────────────────────────────────────────────────────

_AZUL      = colors.HexColor('#1a56db')
_GRIS_OSC  = colors.HexColor('#374151')
_GRIS_MED  = colors.HexColor('#6b7280')
_GRIS_CLR  = colors.HexColor('#f3f4f6')
_NARANJA   = colors.HexColor('#f59e0b')

_TIPOS_TITULO = {
    'FACTURA':      'FACTURA ELECTRÓNICA',
    'BOLETA':       'BOLETA DE VENTA ELECTRÓNICA',
    'NOTA_CREDITO': 'NOTA DE CRÉDITO ELECTRÓNICA',
    'NOTA_DEBITO':  'NOTA DE DÉBITO ELECTRÓNICA',
}


# ─────────────────────────────────────────────────────────────────────────────
# Función principal
# ─────────────────────────────────────────────────────────────────────────────

def generar_pdf(comprobante) -> bytes:
    """Genera el PDF de un comprobante y devuelve los bytes.

    Args:
        comprobante: Objeto Comprobante de SQLAlchemy (con items y cliente cargados).

    Returns:
        bytes: PDF listo para enviar al navegador o guardar en disco.
    """
    cfg = current_app.config
    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=20 * mm,
        title=comprobante.numero_completo,
        author=cfg.get('EMPRESA_RAZON_SOCIAL', ''),
    )

    styles = _build_styles()
    story  = []

    # ── Encabezado (empresa + número comprobante) ──
    story += _seccion_encabezado(comprobante, cfg, styles)
    story.append(Spacer(1, 4 * mm))

    # ── Info cliente ──
    story += _seccion_cliente(comprobante, styles)
    story.append(Spacer(1, 4 * mm))

    # ── Referencia (NC/ND) ──
    if comprobante.comprobante_ref:
        story += _seccion_referencia(comprobante, styles)
        story.append(Spacer(1, 4 * mm))

    # ── Tabla de ítems ──
    story += _seccion_items(comprobante, styles)
    story.append(Spacer(1, 4 * mm))

    # ── Totales + QR ──
    story += _seccion_totales_y_qr(comprobante, cfg, styles)
    story.append(Spacer(1, 5 * mm))

    # ── Pie de página ──
    story += _seccion_pie(comprobante, cfg, styles)

    doc.build(story)
    buffer.seek(0)
    return buffer.read()


# ─────────────────────────────────────────────────────────────────────────────
# Secciones del PDF
# ─────────────────────────────────────────────────────────────────────────────

def _seccion_encabezado(comp, cfg, styles) -> list:
    """Encabezado: logo + empresa a la izquierda, número de comprobante a la derecha."""
    import os
    titulo = _TIPOS_TITULO.get(comp.tipo_comprobante, comp.tipo_comprobante)

    # Logo (opcional) + datos empresa (columna izq)
    empresa_lines = []

    logo_path = os.path.join(current_app.root_path, 'static', 'img', 'logo.png')
    if os.path.exists(logo_path):
        try:
            from PIL import Image as PILImage
            pil_img = PILImage.open(logo_path)
            if pil_img.mode in ('RGBA', 'LA', 'P'):
                bg = PILImage.new('RGB', pil_img.size, (255, 255, 255))
                mask = pil_img.split()[-1] if pil_img.mode in ('RGBA', 'LA') else None
                bg.paste(pil_img.convert('RGBA'), mask=mask)
                pil_img = bg
            elif pil_img.mode != 'RGB':
                pil_img = pil_img.convert('RGB')
            # Guardar en archivo temporal — BytesIO puede fallar en ReportLab
            import tempfile
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                tmp_path = tmp.name
                pil_img.save(tmp_path, format='PNG')
            empresa_lines.append(Image(tmp_path, width=40 * mm, height=20 * mm, kind='proportional'))
        except Exception as e:
            current_app.logger.warning(f'[PDF] Logo no renderizado: {e}')
        empresa_lines.append(Spacer(1, 2 * mm))

    empresa_lines += [
        Paragraph(cfg.get('EMPRESA_RAZON_SOCIAL', ''), styles['empresa_nombre']),
        Paragraph(f"RUC: {cfg.get('EMPRESA_RUC', '')}", styles['empresa_dato']),
    ]
    if cfg.get('EMPRESA_DIRECCION'):
        empresa_lines.append(Paragraph(cfg['EMPRESA_DIRECCION'], styles['empresa_dato']))
    if cfg.get('EMPRESA_TELEFONO'):
        empresa_lines.append(Paragraph(f"Tel: {cfg['EMPRESA_TELEFONO']}", styles['empresa_dato']))
    if cfg.get('EMPRESA_EMAIL'):
        empresa_lines.append(Paragraph(cfg['EMPRESA_EMAIL'], styles['empresa_dato']))

    # Bloque número (columna der)
    numero_lines = [
        Paragraph(titulo, styles['comp_titulo']),
        Paragraph(comp.numero_sunat, styles['comp_numero']),
    ]
    fecha_str = comp.fecha_emision.strftime('%d/%m/%Y')
    numero_lines.append(Paragraph(f'Fecha: {fecha_str}', styles['comp_dato']))
    if comp.numero_orden:
        numero_lines.append(Paragraph(f'Orden: {comp.numero_orden}', styles['comp_dato']))

    tabla = Table(
        [[empresa_lines, numero_lines]],
        colWidths=[110 * mm, 65 * mm],
    )
    tabla.setStyle(TableStyle([
        ('VALIGN',  (0, 0), (-1, -1), 'TOP'),
        ('ALIGN',   (1, 0), (1, 0), 'CENTER'),
        ('BOX',     (1, 0), (1, 0), 1, _AZUL),
        ('BACKGROUND', (1, 0), (1, 0), colors.HexColor('#eff6ff')),
        ('TOPPADDING',  (1, 0), (1, 0), 8),
        ('BOTTOMPADDING', (1, 0), (1, 0), 8),
    ]))
    return [tabla, HRFlowable(width='100%', thickness=1.5, color=_AZUL, spaceAfter=0)]


def _seccion_cliente(comp, styles) -> list:
    cliente = comp.cliente
    data = [
        ['Cliente:', cliente.nombre_completo],
        [f'{cliente.tipo_documento}:', cliente.numero_documento],
    ]
    if cliente.direccion:
        data.append(['Dirección:', cliente.direccion])

    tabla = Table(data, colWidths=[25 * mm, 150 * mm])
    tabla.setStyle(TableStyle([
        ('FONT',    (0, 0), (0, -1), 'Helvetica-Bold', 8),
        ('FONT',    (1, 0), (1, -1), 'Helvetica', 8),
        ('TEXTCOLOR', (0, 0), (0, -1), _GRIS_MED),
        ('TEXTCOLOR', (1, 0), (1, -1), _GRIS_OSC),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    return [tabla]


def _seccion_referencia(comp, styles) -> list:
    ref = comp.comprobante_ref
    data = [
        ['Ref. Comprobante:', ref.numero_sunat],
        ['Motivo:', comp.motivo_descripcion or comp.motivo_codigo or ''],
    ]
    tabla = Table(data, colWidths=[35 * mm, 140 * mm])
    tabla.setStyle(TableStyle([
        ('FONT',    (0, 0), (0, -1), 'Helvetica-Bold', 8),
        ('FONT',    (1, 0), (1, -1), 'Helvetica', 8),
        ('TEXTCOLOR', (0, 0), (0, -1), _GRIS_MED),
        ('TEXTCOLOR', (1, 0), (1, -1), _GRIS_OSC),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('BOX', (0, 0), (-1, -1), 0.5, _NARANJA),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fffbeb')),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    return [tabla]


def _seccion_items(comp, styles) -> list:
    encabezados = ['#', 'Descripción', 'Cant.', 'P.Unit.\n(sin IGV)', 'IGV', 'Subtotal']
    filas = [encabezados]

    for idx, item in enumerate(comp.items, start=1):
        nombre = item.producto_nombre
        if item.producto_sku:
            nombre += f'\n[{item.producto_sku}]'
        filas.append([
            str(idx),
            nombre,
            _fmt(item.cantidad, decimales=0),
            f'S/ {_fmt(item.precio_unitario_sin_igv)}',
            f'S/ {_fmt(item.igv_unitario)}',
            f'S/ {_fmt(item.subtotal_con_igv)}',
        ])

    # Costo de envío como ítem adicional
    if comp.costo_envio and comp.costo_envio > 0:
        from decimal import Decimal, ROUND_HALF_UP
        envio_total = Decimal(str(comp.costo_envio))
        envio_sin_igv = (envio_total / Decimal('1.18')).quantize(Decimal('0.01'), ROUND_HALF_UP)
        envio_igv = (envio_total - envio_sin_igv).quantize(Decimal('0.01'), ROUND_HALF_UP)
        filas.append([
            '—',
            'Costo de envío',
            '1',
            f'S/ {_fmt(envio_sin_igv)}',
            f'S/ {_fmt(envio_igv)}',
            f'S/ {_fmt(envio_total)}',
        ])

    col_w = [8 * mm, 82 * mm, 18 * mm, 28 * mm, 22 * mm, 25 * mm]
    tabla = Table(filas, colWidths=col_w, repeatRows=1)
    style_cmds = [
        # Encabezado
        ('BACKGROUND',    (0, 0), (-1, 0), _AZUL),
        ('TEXTCOLOR',     (0, 0), (-1, 0), colors.white),
        ('FONT',          (0, 0), (-1, 0), 'Helvetica-Bold', 8),
        ('ALIGN',         (0, 0), (-1, 0), 'CENTER'),
        ('TOPPADDING',    (0, 0), (-1, 0), 5),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 5),
        # Cuerpo
        ('FONT',          (0, 1), (-1, -1), 'Helvetica', 8),
        ('TEXTCOLOR',     (0, 1), (-1, -1), _GRIS_OSC),
        ('TOPPADDING',    (0, 1), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 3),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, _GRIS_CLR]),
        # Alineaciones
        ('ALIGN',  (0, 1), (0, -1), 'CENTER'),
        ('ALIGN',  (2, 1), (2, -1), 'CENTER'),
        ('ALIGN',  (3, 1), (5, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        # Bordes
        ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#e5e7eb')),
    ]
    # Fila de envío: fondo y texto diferenciado
    if comp.costo_envio and comp.costo_envio > 0:
        fila_envio = len(filas) - 1
        style_cmds += [
            ('BACKGROUND', (0, fila_envio), (-1, fila_envio), colors.HexColor('#eff6ff')),
            ('FONT',       (1, fila_envio), (1, fila_envio), 'Helvetica-Oblique', 8),
            ('TEXTCOLOR',  (0, fila_envio), (-1, fila_envio), _AZUL),
        ]
    tabla.setStyle(TableStyle(style_cmds))
    return [tabla]


def _seccion_totales_y_qr(comp, cfg, styles) -> list:
    """Tabla dos columnas: QR a la izq, totales a la der."""
    # ── Totales ──
    rows_totales = [
        ('Op. Gravadas', _fmt(comp.total_operaciones_gravadas)),
        ('Op. Exoneradas', _fmt(comp.total_operaciones_exoneradas)),
        ('Op. Inafectas', _fmt(comp.total_operaciones_inafectas)),
        ('I.G.V. 18%', _fmt(comp.total_igv)),
    ]
    if comp.costo_envio and comp.costo_envio > 0:
        rows_totales.append(('Envío (gravado)', _fmt(comp.costo_envio)))

    rows_totales.append(None)  # separador
    rows_totales.append(('IMPORTE TOTAL', f'S/ {_fmt(comp.total)}'))

    # Construir datos tabla totales
    data_tot = []
    for row in rows_totales:
        if row is None:
            data_tot.append(['', ''])
        else:
            etiqueta, valor = row
            es_total = etiqueta == 'IMPORTE TOTAL'
            data_tot.append([
                Paragraph(etiqueta, styles['tot_etiqueta_grand' if es_total else 'tot_etiqueta']),
                Paragraph(f'S/ {valor}' if not valor.startswith('S/') else valor,
                          styles['tot_valor_grand' if es_total else 'tot_valor']),
            ])

    tabla_tot = Table(data_tot, colWidths=[50 * mm, 30 * mm])
    style_tot = [
        ('ALIGN',   (1, 0), (1, -1), 'RIGHT'),
        ('VALIGN',  (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING',    (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('LINEABOVE', (0, -1), (-1, -1), 1, _GRIS_OSC),
        ('BACKGROUND', (0, -1), (-1, -1), _GRIS_CLR),
    ]
    tabla_tot.setStyle(TableStyle(style_tot))

    # ── Son QR ──
    qr_img = _generar_qr(comp, cfg)

    # ── Monto en letras ──
    letras = Paragraph(
        f'<b>SON:</b> {number_to_words_es(comp.total).upper()} SOLES',
        styles['letras'],
    )

    col_qr  = [qr_img, Spacer(1, 2 * mm), Paragraph('Representación impresa de<br/>comprobante electrónico.', styles['pie_qr'])]
    col_tot = [tabla_tot, Spacer(1, 2 * mm), letras]

    tabla_main = Table([[col_qr, col_tot]], colWidths=[45 * mm, 135 * mm])
    tabla_main.setStyle(TableStyle([
        ('VALIGN',  (0, 0), (-1, -1), 'TOP'),
        ('ALIGN',   (0, 0), (0, 0), 'CENTER'),
    ]))
    return [tabla_main]


def _seccion_pie(comp, cfg, styles) -> list:
    partes = [
        Paragraph(
            f'Generado por {cfg.get("EMPRESA_NOMBRE_COMERCIAL", cfg.get("EMPRESA_RAZON_SOCIAL",""))} — '
            f'{datetime.utcnow().strftime("%d/%m/%Y %H:%M")} UTC',
            styles['pie'],
        )
    ]
    if comp.hash_cpe:
        partes.append(Paragraph(f'Hash: {comp.hash_cpe}', styles['pie_hash']))
    return partes


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _generar_qr(comp, cfg) -> Image:
    """Genera imagen QR con los datos SUNAT."""
    ruc        = cfg.get('EMPRESA_RUC', '')
    tipo       = comp.tipo_documento_sunat
    serie      = comp.serie
    correlativo = comp.correlativo.zfill(8)
    igv         = _fmt(comp.total_igv)
    total       = _fmt(comp.total)
    fecha       = comp.fecha_emision.strftime('%Y-%m-%d')
    tipo_doc_cl = comp.cliente.codigo_tipo_documento_sunat
    num_doc_cl  = comp.cliente.numero_documento
    hash_val    = comp.hash_cpe or ''

    qr_data = f'{ruc}|{tipo}|{serie}|{correlativo}|{igv}|{total}|{fecha}|{tipo_doc_cl}|{num_doc_cl}|{hash_val}|'

    qr = qrcode.QRCode(version=1, box_size=3, border=1)
    qr.add_data(qr_data)
    qr.make(fit=True)
    img_pil = qr.make_image(fill_color='black', back_color='white')

    buf = io.BytesIO()
    img_pil.save(buf, format='PNG')
    buf.seek(0)
    return Image(buf, width=38 * mm, height=38 * mm)


def _fmt(valor, decimales: int = 2) -> str:
    if valor is None:
        return '0.00'
    fmt = f'{{:.{decimales}f}}'
    return fmt.format(float(valor))


def _build_styles() -> dict:
    base = getSampleStyleSheet()
    return {
        'empresa_nombre': ParagraphStyle('en', parent=base['Normal'],
            fontSize=11, fontName='Helvetica-Bold', textColor=_GRIS_OSC, leading=14),
        'empresa_dato': ParagraphStyle('ed', parent=base['Normal'],
            fontSize=8, fontName='Helvetica', textColor=_GRIS_MED, leading=11),
        'comp_titulo': ParagraphStyle('ct', parent=base['Normal'],
            fontSize=8.5, fontName='Helvetica-Bold', textColor=_AZUL,
            alignment=TA_CENTER, leading=12),
        'comp_numero': ParagraphStyle('cn', parent=base['Normal'],
            fontSize=13, fontName='Helvetica-Bold', textColor=_GRIS_OSC,
            alignment=TA_CENTER, leading=16),
        'comp_dato': ParagraphStyle('cd', parent=base['Normal'],
            fontSize=8, fontName='Helvetica', textColor=_GRIS_MED,
            alignment=TA_CENTER, leading=11),
        'tot_etiqueta': ParagraphStyle('te', parent=base['Normal'],
            fontSize=8, fontName='Helvetica', textColor=_GRIS_MED),
        'tot_valor': ParagraphStyle('tv', parent=base['Normal'],
            fontSize=8, fontName='Helvetica', textColor=_GRIS_OSC, alignment=TA_RIGHT),
        'tot_etiqueta_grand': ParagraphStyle('teg', parent=base['Normal'],
            fontSize=9.5, fontName='Helvetica-Bold', textColor=_GRIS_OSC),
        'tot_valor_grand': ParagraphStyle('tvg', parent=base['Normal'],
            fontSize=9.5, fontName='Helvetica-Bold', textColor=_AZUL, alignment=TA_RIGHT),
        'letras': ParagraphStyle('lt', parent=base['Normal'],
            fontSize=7.5, fontName='Helvetica', textColor=_GRIS_MED,
            borderPad=4, borderColor=_GRIS_CLR, borderWidth=0.5,
            backColor=_GRIS_CLR),
        'pie': ParagraphStyle('pie', parent=base['Normal'],
            fontSize=7, fontName='Helvetica', textColor=_GRIS_MED, alignment=TA_CENTER),
        'pie_hash': ParagraphStyle('ph', parent=base['Normal'],
            fontSize=6.5, fontName='Helvetica', textColor=_GRIS_MED,
            alignment=TA_CENTER, wordWrap='LTR'),
        'pie_qr': ParagraphStyle('pq', parent=base['Normal'],
            fontSize=6.5, fontName='Helvetica', textColor=_GRIS_MED,
            alignment=TA_CENTER),
    }

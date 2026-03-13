"""Utilidades compartidas: conversión de números a letras, helpers IGV."""
from decimal import Decimal, ROUND_HALF_UP

IGV_RATE = Decimal('0.18')
IGV_DIVISOR = Decimal('1.18')

# ─────────────────────────────────────────────────────────────────────────────
# Cálculos IGV
# ─────────────────────────────────────────────────────────────────────────────

def calcular_igv_item(
    precio_con_igv: Decimal,
    cantidad: Decimal,
    tipo_afectacion: str = '10',
) -> dict:
    """
    Calcula el desglose de IGV para un ítem.
    Los precios de WooCommerce INCLUYEN IGV.

    tipo_afectacion:
        '10' = Gravado (default)
        '20' = Exonerado
        '30' = Inafecto
    """
    precio_con_igv = Decimal(str(precio_con_igv))
    cantidad = Decimal(str(cantidad))

    if tipo_afectacion == '10':  # Gravado
        precio_sin_igv = (precio_con_igv / IGV_DIVISOR).quantize(Decimal('0.01'), ROUND_HALF_UP)
        igv_unitario = (precio_con_igv - precio_sin_igv).quantize(Decimal('0.01'), ROUND_HALF_UP)
    else:  # Exonerado / Inafecto / Exportación
        precio_sin_igv = precio_con_igv
        igv_unitario = Decimal('0.00')

    subtotal_sin_igv = (precio_sin_igv * cantidad).quantize(Decimal('0.01'), ROUND_HALF_UP)
    igv_total = (igv_unitario * cantidad).quantize(Decimal('0.01'), ROUND_HALF_UP)
    subtotal_con_igv = (subtotal_sin_igv + igv_total).quantize(Decimal('0.01'), ROUND_HALF_UP)

    return {
        'precio_sin_igv': precio_sin_igv,
        'igv_unitario': igv_unitario,
        'subtotal_sin_igv': subtotal_sin_igv,
        'igv_total': igv_total,
        'subtotal_con_igv': subtotal_con_igv,
    }


def calcular_totales_comprobante(
    items: list,
    costo_envio: Decimal = Decimal('0'),
    descuento: Decimal = Decimal('0'),
) -> dict:
    """
    Calcula los totales tributarios del comprobante a partir de sus ítems.
    El envío siempre se trata como operación gravada.

    El descuento es un descuento global post-impuesto (se resta solo del total
    final). Las bases gravadas e IGV se almacenan en sus valores originales para
    que coincidan con la sumatoria de líneas en el XML (evita error SUNAT 3277).
    """
    costo_envio = Decimal(str(costo_envio))
    descuento   = Decimal(str(descuento))

    _D0 = Decimal('0')
    total_gravadas   = sum((Decimal(str(i.subtotal_sin_igv)) for i in items if i.tipo_afectacion_igv == '10'), _D0)
    total_exoneradas = sum((Decimal(str(i.subtotal_sin_igv)) for i in items if i.tipo_afectacion_igv == '20'), _D0)
    total_inafectas  = sum((Decimal(str(i.subtotal_sin_igv)) for i in items if i.tipo_afectacion_igv == '30'), _D0)
    total_igv        = sum((Decimal(str(i.igv_total)) for i in items if i.tipo_afectacion_igv == '10'), _D0)

    if costo_envio > 0:
        envio_sin_igv = (costo_envio / IGV_DIVISOR).quantize(Decimal('0.01'), ROUND_HALF_UP)
        igv_envio = (costo_envio - envio_sin_igv).quantize(Decimal('0.01'), ROUND_HALF_UP)
        total_gravadas += envio_sin_igv
        total_igv += igv_envio

    # El descuento reduce solo el total final (PayableAmount en UBL).
    # total_gravadas y total_igv mantienen sus valores originales para
    # que TaxSubtotal/TaxableAmount coincida con la suma de líneas.
    total_bruto = total_gravadas + total_exoneradas + total_inafectas + total_igv
    total = total_bruto - descuento

    descuento_sin_igv = (descuento / IGV_DIVISOR).quantize(Decimal('0.01'), ROUND_HALF_UP) if descuento > _D0 else _D0

    return {
        'total_gravadas':    total_gravadas.quantize(Decimal('0.01')),
        'total_exoneradas':  total_exoneradas.quantize(Decimal('0.01')),
        'total_inafectas':   total_inafectas.quantize(Decimal('0.01')),
        'total_igv':         total_igv.quantize(Decimal('0.01')),
        'total':             total.quantize(Decimal('0.01')),
        'descuento_sin_igv': descuento_sin_igv,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Número a letras (Soles peruanos)
# ─────────────────────────────────────────────────────────────────────────────

UNIDADES = ['', 'UN', 'DOS', 'TRES', 'CUATRO', 'CINCO', 'SEIS', 'SIETE', 'OCHO', 'NUEVE']
DECENAS  = ['', 'DIEZ', 'VEINTE', 'TREINTA', 'CUARENTA', 'CINCUENTA',
            'SESENTA', 'SETENTA', 'OCHENTA', 'NOVENTA']
ESPECIALES = {
    11: 'ONCE', 12: 'DOCE', 13: 'TRECE', 14: 'CATORCE', 15: 'QUINCE',
    16: 'DIECISEIS', 17: 'DIECISIETE', 18: 'DIECIOCHO', 19: 'DIECINUEVE',
}
CENTENAS = ['', 'CIEN', 'DOSCIENTOS', 'TRESCIENTOS', 'CUATROCIENTOS', 'QUINIENTOS',
            'SEISCIENTOS', 'SETECIENTOS', 'OCHOCIENTOS', 'NOVECIENTOS']


def _grupos(n: int) -> str:
    if n == 0:
        return ''
    if n == 100:
        return 'CIEN'
    result = ''
    c = n // 100
    if c:
        result += CENTENAS[c] + ' '
        n = n % 100
    if n in ESPECIALES:
        result += ESPECIALES[n]
    elif n >= 10:
        d = n // 10
        u = n % 10
        result += DECENAS[d]
        if u:
            result += ' Y ' + UNIDADES[u]
    else:
        result += UNIDADES[n]
    return result.strip()


def number_to_words_es(amount: Decimal) -> str:
    """Convierte un monto decimal a texto en español (Soles peruanos).

    Ejemplo: 1015.00 → 'MIL QUINCE CON 00/100 SOLES'
    """
    amount = Decimal(str(amount)).quantize(Decimal('0.01'), ROUND_HALF_UP)
    entero = int(amount)
    centavos = int((amount - entero) * 100)

    if entero == 0:
        texto = 'CERO'
    elif entero == 1:
        texto = 'UN'
    else:
        partes = []
        millones = entero // 1_000_000
        resto = entero % 1_000_000
        miles = resto // 1000
        centenas = resto % 1000

        if millones == 1:
            partes.append('UN MILLON')
        elif millones > 1:
            partes.append(_grupos(millones) + ' MILLONES')

        if miles == 1:
            partes.append('MIL')
        elif miles > 1:
            partes.append(_grupos(miles) + ' MIL')

        if centenas:
            partes.append(_grupos(centenas))

        texto = ' '.join(p for p in partes if p)

    return f"{texto} CON {centavos:02d}/100 SOLES"


# ─────────────────────────────────────────────────────────────────────────────
# Validaciones de fecha SUNAT
# ─────────────────────────────────────────────────────────────────────────────

from datetime import date, timedelta


def validar_fecha_correlativo(serie: str, fecha_emision) -> str | None:
    """
    Regla SUNAT: el nuevo comprobante no puede tener fecha_emision anterior
    al último comprobante emitido en la misma serie.

    Retorna mensaje de error (str) si la fecha es inválida, None si es válida.
    """
    from app.extensions import db
    from app.models.comprobante import Comprobante
    ultima_fecha = (
        db.session.query(db.func.max(Comprobante.fecha_emision))
        .filter(Comprobante.serie == serie)
        .scalar()
    )
    if ultima_fecha and fecha_emision.date() < ultima_fecha.date():
        return (
            f'La fecha {fecha_emision.strftime("%d/%m/%Y")} es anterior al '
            f'último comprobante de la serie {serie} '
            f'({ultima_fecha.strftime("%d/%m/%Y")}). '
            f'Los correlativos deben emitirse en orden cronológico (norma SUNAT).'
        )
    return None


def validar_fecha_atraso(tipo_comprobante: str, fecha_emision) -> str | None:
    """
    Regla SUNAT: máximo 7 días de atraso para boletas, 3 para facturas.
    NCs, NDs y otros tipos no aplican esta regla.

    Retorna mensaje de error (str) si la fecha es inválida, None si es válida.
    """
    _LIMITES = {'BOLETA': 7, 'FACTURA': 3}
    limite = _LIMITES.get(tipo_comprobante)
    if limite is None:
        return None
    hoy = date.today()
    fecha_minima = hoy - timedelta(days=limite)
    if fecha_emision.date() < fecha_minima:
        return (
            f'La fecha {fecha_emision.strftime("%d/%m/%Y")} supera el límite '
            f'de {limite} días de atraso permitidos para {tipo_comprobante} '
            f'(norma SUNAT). Fecha mínima permitida: {fecha_minima.strftime("%d/%m/%Y")}.'
        )
    return None


def extraer_skus_base(sku_woo: str) -> list:
    """Extrae segmentos numéricos de 7 u 8 dígitos de un SKU compuesto.

    Ej: '1003226-1007031-S1046' → ['1003226', '1007031']
        '1003226'               → ['1003226']
        'ENVIO'                 → []
    """
    import re
    if not sku_woo:
        return []
    partes = str(sku_woo).split('-')
    return [p for p in partes if re.fullmatch(r'\d{7,8}', p)]

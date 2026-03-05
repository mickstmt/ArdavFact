"""Generación de XML UBL 2.1 para SUNAT.

Soporta:
  - Factura Electrónica (tipo 01)
  - Boleta de Venta Electrónica (tipo 03)
  - Nota de Crédito Electrónica (tipo 07)
  - Nota de Débito Electrónica (tipo 08)

IGV 18% — los precios en BD ya tienen IGV incluido:
  precio_sin_igv = precio_con_igv / 1.18
  igv            = precio_con_igv - precio_sin_igv
"""
import base64
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from lxml import etree
from flask import current_app

# ─────────────────────────────────────────────────────────────────────────────
# Namespaces UBL 2.1
# ─────────────────────────────────────────────────────────────────────────────

_CAC = 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2'
_CBC = 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2'
_EXT = 'urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2'
_DS  = 'http://www.w3.org/2000/09/xmldsig#'

_NS_INVOICE     = 'urn:oasis:names:specification:ubl:schema:xsd:Invoice-2'
_NS_CREDIT_NOTE = 'urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2'
_NS_DEBIT_NOTE  = 'urn:oasis:names:specification:ubl:schema:xsd:DebitNote-2'

_NSMAP_BASE = {
    'cac': _CAC,
    'cbc': _CBC,
    'ext': _EXT,
    'ds':  _DS,
}

# ─────────────────────────────────────────────────────────────────────────────
# Catálogos SUNAT
# ─────────────────────────────────────────────────────────────────────────────

# Catálogo 07 — tipo afectación → (TaxExemptionReasonCode, tax_code, tax_name, tax_type_code)
_AFECTACION = {
    '10': ('10', '1000', 'IGV',  'VAT'),   # Gravado oneroso
    '11': ('11', '1000', 'IGV',  'VAT'),   # Gravado retiro
    '20': ('20', '9997', 'EXO',  'VAT'),   # Exonerado oneroso
    '21': ('21', '9997', 'EXO',  'VAT'),   # Exonerado retiro
    '30': ('30', '9998', 'INA',  'FRE'),   # Inafecto oneroso
    '31': ('31', '9998', 'INA',  'FRE'),   # Inafecto retiro
    '40': ('40', '9995', 'EXP',  'FRE'),   # Exportación
}

# Catálogo 09 — motivos Nota de Crédito
MOTIVOS_NC = {
    '01': 'Anulación de la operación',
    '02': 'Anulación por error en el RUC',
    '03': 'Corrección por error en la descripción',
    '04': 'Descuento global',
    '05': 'Descuento por ítem',
    '06': 'Devolución total',
    '07': 'Devolución por ítem',
    '08': 'Bonificación',
    '09': 'Disminución en el valor',
}

# Catálogo 10 — motivos Nota de Débito
MOTIVOS_ND = {
    '01': 'Intereses por mora',
    '02': 'Aumento en el valor',
    '03': 'Penalidades / otros conceptos',
}


# ─────────────────────────────────────────────────────────────────────────────
# Funciones públicas
# ─────────────────────────────────────────────────────────────────────────────

def nombre_archivo(comprobante) -> str:
    """Nombre del archivo para MiPSE/SUNAT (sin extensión).

    Formato: {RUC_EMISOR}-{TIPO_DOC}-{SERIE}-{CORRELATIVO_8D}
    Ejemplo: 20605555790-01-F001-00000001
    """
    ruc = current_app.config.get('EMPRESA_RUC', '20605555790')
    correlativo = str(comprobante.correlativo).zfill(8)
    return f"{ruc}-{comprobante.tipo_documento_sunat}-{comprobante.serie}-{correlativo}"


def generar_xml(comprobante) -> bytes:
    """Genera XML UBL 2.1 completo listo para enviar a MiPSE.

    Returns:
        bytes: XML codificado en ISO-8859-1.
    """
    tipo = comprobante.tipo_documento_sunat
    if tipo in ('01', '03'):
        root = _generar_invoice(comprobante)
    elif tipo == '07':
        root = _generar_credit_note(comprobante)
    elif tipo == '08':
        root = _generar_debit_note(comprobante)
    else:
        raise ValueError(f'Tipo de comprobante no soportado: {tipo}')

    return etree.tostring(
        root,
        xml_declaration=True,
        encoding='ISO-8859-1',
        pretty_print=True,
    )


def generar_xml_b64(comprobante) -> str:
    """Genera XML y lo devuelve en base64 (para enviar a MiPSE)."""
    xml_bytes = generar_xml(comprobante)
    return base64.b64encode(xml_bytes).decode('ascii')


# ─────────────────────────────────────────────────────────────────────────────
# Generadores por tipo de comprobante
# ─────────────────────────────────────────────────────────────────────────────

def _generar_invoice(comprobante) -> etree.Element:
    """Genera XML de Factura (01) o Boleta (03)."""
    nsmap = {None: _NS_INVOICE, **_NSMAP_BASE}
    root = etree.Element(f'{{{_NS_INVOICE}}}Invoice', nsmap=nsmap)

    cfg = current_app.config
    cliente = comprobante.cliente

    _add_ublextensions(root)
    _cbc(root, 'UBLVersionID', '2.1')
    _cbc(root, 'CustomizationID', '2.0')
    _cbc(root, 'ID', comprobante.numero_sunat)
    _cbc(root, 'IssueDate', comprobante.fecha_emision.strftime('%Y-%m-%d'))
    _cbc(root, 'IssueTime', comprobante.fecha_emision.strftime('%H:%M:%S'))

    # DueDate solo para facturas (30 días por defecto)
    if comprobante.tipo_documento_sunat == '01':
        from datetime import timedelta
        venc = comprobante.fecha_vencimiento or (comprobante.fecha_emision + timedelta(days=30))
        _cbc(root, 'DueDate', venc.strftime('%Y-%m-%d'))

    tipo_el = _cbc(root, 'InvoiceTypeCode', comprobante.tipo_documento_sunat)
    tipo_el.set('listAgencyName', 'PE:SUNAT')
    tipo_el.set('listID', '0101')
    tipo_el.set('listName', 'Tipo de Documento')
    tipo_el.set('listSchemeURI', 'urn:pe:gob:sunat:cpe:see:gem:catalogos:catalogo51')
    tipo_el.set('listURI', 'urn:pe:gob:sunat:cpe:see:gem:catalogos:catalogo01')
    tipo_el.set('name', 'Tipo de Operacion')

    curr_el = _cbc(root, 'DocumentCurrencyCode', 'PEN')
    curr_el.set('listAgencyName', 'United Nations Economic Commission for Europe')
    curr_el.set('listID', 'ISO 4217 Alpha')
    curr_el.set('listName', 'Currency')

    # Número de orden (referencia WooCommerce)
    if comprobante.numero_orden:
        _add_order_reference(root, comprobante.numero_orden)

    _add_signature(root, cfg)
    _add_supplier_party(root, cfg)
    _add_customer_party(root, cliente)
    _add_payment_terms(root, comprobante)
    _add_charge_global(root, comprobante)
    _add_tax_total(root, comprobante)
    _add_legal_monetary_total(root, comprobante)

    for idx, item in enumerate(comprobante.items, start=1):
        _add_invoice_line(root, item, idx)

    return root


def _generar_credit_note(comprobante) -> etree.Element:
    """Genera XML de Nota de Crédito (07)."""
    nsmap = {None: _NS_CREDIT_NOTE, **_NSMAP_BASE}
    root = etree.Element(f'{{{_NS_CREDIT_NOTE}}}CreditNote', nsmap=nsmap)

    cfg = current_app.config
    cliente = comprobante.cliente

    _add_ublextensions(root)
    _cbc(root, 'UBLVersionID', '2.1')
    _cbc(root, 'CustomizationID', '2.0')
    _cbc(root, 'ID', comprobante.numero_sunat)
    _cbc(root, 'IssueDate', comprobante.fecha_emision.strftime('%Y-%m-%d'))
    _cbc(root, 'IssueTime', comprobante.fecha_emision.strftime('%H:%M:%S'))
    _cbc(root, 'DocumentCurrencyCode', 'PEN')

    # Motivo
    motivo_codigo = comprobante.motivo_codigo or '01'
    motivo_desc   = comprobante.motivo_descripcion or MOTIVOS_NC.get(motivo_codigo, '')
    dr = _cac(root, 'DiscrepancyResponse')
    _cbc(dr, 'ReferenceID', comprobante.comprobante_ref.numero_sunat if comprobante.comprobante_ref else '')
    _cbc(dr, 'ResponseCode', motivo_codigo)
    _cbc(dr, 'Description', motivo_desc)

    # Referencia al comprobante original
    if comprobante.comprobante_ref:
        _add_billing_reference(root, comprobante.comprobante_ref)

    _add_signature(root, cfg)
    _add_supplier_party(root, cfg)
    _add_customer_party(root, cliente)
    _add_tax_total(root, comprobante)
    _add_legal_monetary_total(root, comprobante)

    for idx, item in enumerate(comprobante.items, start=1):
        _add_credit_note_line(root, item, idx)

    return root


def _generar_debit_note(comprobante) -> etree.Element:
    """Genera XML de Nota de Débito (08)."""
    nsmap = {None: _NS_DEBIT_NOTE, **_NSMAP_BASE}
    root = etree.Element(f'{{{_NS_DEBIT_NOTE}}}DebitNote', nsmap=nsmap)

    cfg = current_app.config
    cliente = comprobante.cliente

    _add_ublextensions(root)
    _cbc(root, 'UBLVersionID', '2.1')
    _cbc(root, 'CustomizationID', '2.0')
    _cbc(root, 'ID', comprobante.numero_sunat)
    _cbc(root, 'IssueDate', comprobante.fecha_emision.strftime('%Y-%m-%d'))
    _cbc(root, 'IssueTime', comprobante.fecha_emision.strftime('%H:%M:%S'))
    _cbc(root, 'DocumentCurrencyCode', 'PEN')

    # Motivo
    motivo_codigo = comprobante.motivo_codigo or '01'
    motivo_desc   = comprobante.motivo_descripcion or MOTIVOS_ND.get(motivo_codigo, '')
    dr = _cac(root, 'DiscrepancyResponse')
    _cbc(dr, 'ReferenceID', comprobante.comprobante_ref.numero_sunat if comprobante.comprobante_ref else '')
    _cbc(dr, 'ResponseCode', motivo_codigo)
    _cbc(dr, 'Description', motivo_desc)

    # Referencia al comprobante original
    if comprobante.comprobante_ref:
        _add_billing_reference(root, comprobante.comprobante_ref)

    _add_signature(root, cfg)
    _add_supplier_party(root, cfg)
    _add_customer_party(root, cliente)
    _add_tax_total(root, comprobante)
    _add_legal_monetary_total(root, comprobante)

    for idx, item in enumerate(comprobante.items, start=1):
        _add_debit_note_line(root, item, idx)

    return root


# ─────────────────────────────────────────────────────────────────────────────
# Builders de secciones comunes
# ─────────────────────────────────────────────────────────────────────────────

def _add_ublextensions(root: etree.Element):
    """Placeholder para firma digital (se rellena por MiPSE)."""
    exts = etree.SubElement(root, f'{{{_EXT}}}UBLExtensions')
    ext  = etree.SubElement(exts, f'{{{_EXT}}}UBLExtension')
    etree.SubElement(ext, f'{{{_EXT}}}ExtensionContent')


def _add_order_reference(root: etree.Element, numero_orden: str):
    or_el = _cac(root, 'OrderReference')
    _cbc(or_el, 'ID', numero_orden)


def _add_signature(root: etree.Element, cfg):
    """Nodo Signature (se firma por MiPSE)."""
    ruc = cfg.get('EMPRESA_RUC', '')
    sig = _cac(root, 'Signature')
    _cbc(sig, 'ID', ruc)
    _cbc(sig, 'Note', 'Elaborado por Sistema de Emision Electronica Facturador SUNAT (SEE-SFS) 1.4')
    sp = _cac(sig, 'SignatoryParty')
    pi = _cac(sp,  'PartyIdentification')
    _cbc(pi, 'ID', ruc)
    pn = _cac(sp, 'PartyName')
    _cbc(pn, 'Name', cfg.get('EMPRESA_RAZON_SOCIAL', ''))
    da = _cac(sig, 'DigitalSignatureAttachment')
    er = _cac(da, 'ExternalReference')
    _cbc(er, 'URI', 'SIGN')


def _add_supplier_party(root: etree.Element, cfg):
    """AccountingSupplierParty — el emisor (empresa)."""
    asp = _cac(root, 'AccountingSupplierParty')
    party = _cac(asp, 'Party')

    pi = _cac(party, 'PartyIdentification')
    ruc_el = _cbc(pi, 'ID', cfg.get('EMPRESA_RUC', ''))
    ruc_el.set('schemeAgencyName', 'PE:SUNAT')
    ruc_el.set('schemeID', '6')
    ruc_el.set('schemeName', 'Documento de Identidad')
    ruc_el.set('schemeURI', 'urn:pe:gob:sunat:cpe:see:gem:catalogos:catalogo06')

    pn = _cac(party, 'PartyName')
    _cbc(pn, 'Name', cfg.get('EMPRESA_NOMBRE_COMERCIAL', cfg.get('EMPRESA_RAZON_SOCIAL', '')))

    # PostalAddress directamente bajo Party (requerido por SUNAT, incluye ubigeo)
    pa = _cac(party, 'PostalAddress')
    _cbc(pa, 'ID', cfg.get('EMPRESA_UBIGEO', ''))
    atc = _cbc(pa, 'AddressTypeCode', '0000')
    atc.set('listAgencyName', 'PE:SUNAT')
    atc.set('listName', 'Establecimientos anexos')
    _cbc(pa, 'StreetName', cfg.get('EMPRESA_DIRECCION', ''))
    country = _cac(pa, 'Country')
    _cbc(country, 'IdentificationCode', 'PE')

    ple = _cac(party, 'PartyLegalEntity')
    _cbc(ple, 'RegistrationName', cfg.get('EMPRESA_RAZON_SOCIAL', ''))
    reg_addr = _cac(ple, 'RegistrationAddress')
    atc = _cbc(reg_addr, 'AddressTypeCode', '0000')
    atc.set('listAgencyName', 'PE:SUNAT')
    atc.set('listName', 'Establecimientos anexos')


def _add_customer_party(root: etree.Element, cliente):
    """AccountingCustomerParty — el receptor (cliente)."""
    acp = _cac(root, 'AccountingCustomerParty')
    party = _cac(acp, 'Party')

    pi = _cac(party, 'PartyIdentification')
    doc_el = _cbc(pi, 'ID', cliente.numero_documento)
    doc_el.set('schemeAgencyName', 'PE:SUNAT')
    doc_el.set('schemeID', cliente.codigo_tipo_documento_sunat)
    doc_el.set('schemeName', 'Documento de Identidad')
    doc_el.set('schemeURI', 'urn:pe:gob:sunat:cpe:see:gem:catalogos:catalogo06')

    ple = _cac(party, 'PartyLegalEntity')
    _cbc(ple, 'RegistrationName', cliente.nombre_completo)

    if cliente.direccion:
        ra = _cac(ple, 'RegistrationAddress')
        _cbc(ra, 'StreetName', cliente.direccion)
        country = _cac(ra, 'Country')
        _cbc(country, 'IdentificationCode', 'PE')


def _add_billing_reference(root: etree.Element, comp_ref):
    """BillingReference para NC/ND — referencia al comprobante original."""
    br = _cac(root, 'BillingReference')
    ir = _cac(br, 'InvoiceDocumentReference')
    _cbc(ir, 'ID', comp_ref.numero_sunat)
    _cbc(ir, 'DocumentTypeCode', comp_ref.tipo_documento_sunat)


def _add_charge_global(root: etree.Element, comprobante):
    """AllowanceCharge global para el costo de envío (ChargeIndicator=true).

    SUNAT requiere que ChargeTotalAmount en LegalMonetaryTotal coincida con
    la suma de AllowanceCharge con ChargeIndicator=true. Amount = envío CON IGV.
    """
    envio = _d(comprobante.costo_envio)
    if envio <= Decimal('0'):
        return
    ac = _cac(root, 'AllowanceCharge')
    _cbc(ac, 'ChargeIndicator', 'true')
    rc = _cbc(ac, 'AllowanceChargeReasonCode', '02')  # 02 = Flete (Catálogo 53)
    rc.set('listAgencyName', 'PE:SUNAT')
    rc.set('listName', 'Cargo/descuento')
    rc.set('listURI', 'urn:pe:gob:sunat:cpe:see:gem:catalogos:catalogo53')
    _cbc(ac, 'AllowanceChargeReason', 'Costo de Envío')
    _amt(ac, 'Amount', envio)


def _add_allowance_charge(root: etree.Element, comprobante):
    """AllowanceCharge de descuento global — solo si hay descuento."""
    descuento = _d(comprobante.descuento)
    if descuento <= Decimal('0'):
        return
    # Amount debe coincidir con AllowanceTotalAmount en LegalMonetaryTotal.
    # Ambos = descuento con IGV (monto completo visible al usuario).
    # BaseAmount = total bruto con IGV antes del descuento.
    gravadas   = _d(comprobante.total_operaciones_gravadas)
    igv        = _d(comprobante.total_igv)
    exoneradas = _d(comprobante.total_operaciones_exoneradas)
    inafectas  = _d(comprobante.total_operaciones_inafectas)
    total_bruto = gravadas + exoneradas + inafectas + igv
    ac = _cac(root, 'AllowanceCharge')
    _cbc(ac, 'ChargeIndicator', 'false')
    rc = _cbc(ac, 'AllowanceChargeReasonCode', '00')
    rc.set('listAgencyName', 'PE:SUNAT')
    rc.set('listName', 'Cargo/descuento')
    rc.set('listURI', 'urn:pe:gob:sunat:cpe:see:gem:catalogos:catalogo53')
    _cbc(ac, 'AllowanceChargeReason', 'Descuento Global')
    _amt(ac, 'Amount', descuento)
    _amt(ac, 'BaseAmount', total_bruto)


def _add_payment_terms(root: etree.Element, comprobante):
    """PaymentTerms — Indica si es al Contado o Crédito (Requerido SUNAT 3244)."""
    es_credito = (
        comprobante.tipo_comprobante == 'FACTURA' and
        comprobante.fecha_vencimiento and
        comprobante.fecha_vencimiento.date() > comprobante.fecha_emision.date()
    )

    pt = _cac(root, 'PaymentTerms')
    _cbc(pt, 'ID', 'Credito' if es_credito else 'FormaPago')
    _cbc(pt, 'PaymentMeansID', 'Credito' if es_credito else 'Contado')
    _amt(pt, 'Amount', _d(comprobante.total))

    if es_credito:
        pt2 = _cac(root, 'PaymentTerms')
        _cbc(pt2, 'ID', 'FormaPago')
        _cbc(pt2, 'PaymentMeansID', 'Cuota001')
        _amt(pt2, 'Amount', _d(comprobante.total))
        _cbc(pt2, 'PaymentDueDate', comprobante.fecha_vencimiento.strftime('%Y-%m-%d'))


def _add_tax_total(root: etree.Element, comprobante):
    """TaxTotal global del comprobante.

    SUNAT (4299/4290): TaxableAmount y TaxAmount deben coincidir con la suma
    de los TaxTotal de línea — NO incluir el envío (va como AllowanceCharge).
    """
    tt = _cac(root, 'TaxTotal')

    # Separar IGV y base del envío para excluirlos del TaxTotal de líneas
    envio = _d(comprobante.costo_envio)
    if envio > 0:
        envio_sin_igv = (envio / Decimal('1.18')).quantize(Decimal('0.01'), ROUND_HALF_UP)
        envio_igv = envio - envio_sin_igv
    else:
        envio_sin_igv = Decimal('0.00')
        envio_igv = Decimal('0.00')

    igv_items = (_d(comprobante.total_igv) - envio_igv).quantize(Decimal('0.01'), ROUND_HALF_UP)
    _amt(tt, 'TaxAmount', igv_items)

    # Subtotal gravado (IGV 18%) — solo ítems, sin envío
    gravadas_items = (_d(comprobante.total_operaciones_gravadas) - envio_sin_igv).quantize(Decimal('0.01'), ROUND_HALF_UP)
    if gravadas_items > 0:
        _add_tax_subtotal(tt, gravadas_items, igv_items, '10')

    # Subtotal exonerado
    exoneradas = _d(comprobante.total_operaciones_exoneradas)
    if exoneradas > 0:
        _add_tax_subtotal(tt, exoneradas, Decimal('0.00'), '20')

    # Subtotal inafecto
    inafectas = _d(comprobante.total_operaciones_inafectas)
    if inafectas > 0:
        _add_tax_subtotal(tt, inafectas, Decimal('0.00'), '30')


def _add_tax_subtotal(parent: etree.Element, base: Decimal, igv: Decimal, afectacion: str):
    """TaxSubtotal dentro de TaxTotal."""
    exemption_code, tax_code, tax_name, tax_type = _AFECTACION[afectacion]
    ts = _cac(parent, 'TaxSubtotal')
    _amt(ts, 'TaxableAmount', base)
    _amt(ts, 'TaxAmount', igv)
    tc = _cac(ts, 'TaxCategory')
    tscheme = _cac(tc, 'TaxScheme')
    tid = _cbc(tscheme, 'ID', tax_code)
    tid.set('schemeAgencyName', 'PE:SUNAT')
    tid.set('schemeID', 'UN/ECE 5153')
    tid.set('schemeName', 'Codigo de tributos')
    _cbc(tscheme, 'Name', tax_name)
    _cbc(tscheme, 'TaxTypeCode', tax_type)


def _add_legal_monetary_total(root: etree.Element, comprobante):
    """LegalMonetaryTotal — totales monetarios finales.

    Reglas SUNAT:
      4309: LineExtensionAmount = suma LineExtensionAmount de líneas (sin envío)
      4310: TaxInclusiveAmount  = LineExtensionAmount + TaxTotal/TaxAmount (sin envío)
      4308: ChargeTotalAmount   = suma AllowanceCharge[ChargeIndicator=true]/Amount
                                = costo_envio CON IGV
      4312: PayableAmount       = TaxInclusiveAmount + ChargeTotalAmount
    """
    lmt = _cac(root, 'LegalMonetaryTotal')

    envio = _d(comprobante.costo_envio)
    if envio > 0:
        envio_sin_igv = (envio / Decimal('1.18')).quantize(Decimal('0.01'), ROUND_HALF_UP)
        envio_igv = envio - envio_sin_igv
    else:
        envio_sin_igv = Decimal('0.00')
        envio_igv = Decimal('0.00')

    # Valores solo de ítems (excluir envío)
    gravadas_items = (_d(comprobante.total_operaciones_gravadas) - envio_sin_igv).quantize(Decimal('0.01'), ROUND_HALF_UP)
    exoneradas     = _d(comprobante.total_operaciones_exoneradas)
    inafectas      = _d(comprobante.total_operaciones_inafectas)
    igv_items      = (_d(comprobante.total_igv) - envio_igv).quantize(Decimal('0.01'), ROUND_HALF_UP)

    line_ext      = (gravadas_items + exoneradas + inafectas).quantize(Decimal('0.01'), ROUND_HALF_UP)
    tax_inclusive = (line_ext + igv_items).quantize(Decimal('0.01'), ROUND_HALF_UP)

    _amt(lmt, 'LineExtensionAmount', line_ext)
    _amt(lmt, 'TaxInclusiveAmount', tax_inclusive)

    if envio > 0:
        _amt(lmt, 'ChargeTotalAmount', envio)  # CON IGV — coincide con AllowanceCharge/Amount

    _amt(lmt, 'PayableAmount', _d(comprobante.total))


# ─────────────────────────────────────────────────────────────────────────────
# Líneas de comprobante
# ─────────────────────────────────────────────────────────────────────────────

def _add_invoice_line(root: etree.Element, item, idx: int):
    """Línea de InvoiceLine para Factura/Boleta."""
    line = _cac(root, 'InvoiceLine')
    _cbc(line, 'ID', str(idx))

    qty_el = _cbc(line, 'InvoicedQuantity', _fmt(item.cantidad))
    qty_el.set('unitCode', item.unidad_medida or 'NIU')
    qty_el.set('unitCodeListAgencyName', 'United Nations Economic Commission for Europe')
    qty_el.set('unitCodeListID', 'UN/ECE rec 20')

    _amt(line, 'LineExtensionAmount', _d(item.subtotal_sin_igv))
    _add_pricing_reference(line, item)
    _add_item_tax_total(line, item)
    _add_item_description(line, item)
    price = _cac(line, 'Price')
    _amt(price, 'PriceAmount', _d(item.precio_unitario_sin_igv))


def _add_credit_note_line(root: etree.Element, item, idx: int):
    """Línea de CreditNoteLine."""
    line = _cac(root, 'CreditNoteLine')
    _cbc(line, 'ID', str(idx))

    qty_el = _cbc(line, 'CreditedQuantity', _fmt(item.cantidad))
    qty_el.set('unitCode', item.unidad_medida or 'NIU')
    qty_el.set('unitCodeListAgencyName', 'United Nations Economic Commission for Europe')
    qty_el.set('unitCodeListID', 'UN/ECE rec 20')

    _amt(line, 'LineExtensionAmount', _d(item.subtotal_sin_igv))
    _add_pricing_reference(line, item)
    _add_item_tax_total(line, item)
    _add_item_description(line, item)
    price = _cac(line, 'Price')
    _amt(price, 'PriceAmount', _d(item.precio_unitario_sin_igv))


def _add_debit_note_line(root: etree.Element, item, idx: int):
    """Línea de DebitNoteLine."""
    line = _cac(root, 'DebitNoteLine')
    _cbc(line, 'ID', str(idx))

    qty_el = _cbc(line, 'DebitedQuantity', _fmt(item.cantidad))
    qty_el.set('unitCode', item.unidad_medida or 'NIU')
    qty_el.set('unitCodeListAgencyName', 'United Nations Economic Commission for Europe')
    qty_el.set('unitCodeListID', 'UN/ECE rec 20')

    _amt(line, 'LineExtensionAmount', _d(item.subtotal_sin_igv))
    _add_pricing_reference(line, item)
    _add_item_tax_total(line, item)
    _add_item_description(line, item)
    price = _cac(line, 'Price')
    _amt(price, 'PriceAmount', _d(item.precio_unitario_sin_igv))


def _add_pricing_reference(line: etree.Element, item):
    """PricingReference — precio de venta al público (con IGV)."""
    pr = _cac(line, 'PricingReference')
    acp = _cac(pr, 'AlternativeConditionPrice')
    _amt(acp, 'PriceAmount', _d(item.precio_unitario_con_igv))
    ptc = _cbc(acp, 'PriceTypeCode', '01')  # 01 = precio unitario (incluye impuesto)
    ptc.set('listAgencyName', 'PE:SUNAT')
    ptc.set('listName', 'Tipo de Precio')
    ptc.set('listURI', 'urn:pe:gob:sunat:cpe:see:gem:catalogos:catalogo16')


def _add_item_tax_total(line: etree.Element, item):
    """TaxTotal a nivel de línea."""
    afectacion = item.tipo_afectacion_igv or '10'
    exemption_code, tax_code, tax_name, tax_type = _AFECTACION[afectacion]

    tt = _cac(line, 'TaxTotal')
    _amt(tt, 'TaxAmount', _d(item.igv_total))

    ts = _cac(tt, 'TaxSubtotal')
    _amt(ts, 'TaxableAmount', _d(item.subtotal_sin_igv))
    _amt(ts, 'TaxAmount', _d(item.igv_total))

    tc = _cac(ts, 'TaxCategory')
    pct = '18.00' if afectacion in ('10', '11') else '0.00'
    _cbc(tc, 'Percent', pct)
    erc = _cbc(tc, 'TaxExemptionReasonCode', exemption_code)
    erc.set('listAgencyName', 'PE:SUNAT')
    erc.set('listName', 'Afectacion del IGV')
    erc.set('listURI', 'urn:pe:gob:sunat:cpe:see:gem:catalogos:catalogo07')
    tscheme = _cac(tc, 'TaxScheme')
    tid = _cbc(tscheme, 'ID', tax_code)
    tid.set('schemeAgencyName', 'PE:SUNAT')
    tid.set('schemeID', 'UN/ECE 5153')
    tid.set('schemeName', 'Codigo de tributos')
    _cbc(tscheme, 'Name', tax_name)
    _cbc(tscheme, 'TaxTypeCode', tax_type)


def _add_item_description(line: etree.Element, item):
    """Item con descripción y código de producto."""
    it = _cac(line, 'Item')
    _cbc(it, 'Description', item.producto_nombre)
    if item.producto_sku:
        sii = _cac(it, 'SellersItemIdentification')
        _cbc(sii, 'ID', item.producto_sku)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de construcción XML
# ─────────────────────────────────────────────────────────────────────────────

def _cbc(parent: etree.Element, tag: str, text: str = '') -> etree.Element:
    """Crea un elemento cbc:{tag} con el texto dado."""
    el = etree.SubElement(parent, f'{{{_CBC}}}{tag}')
    el.text = str(text) if text is not None else ''
    return el


def _cac(parent: etree.Element, tag: str) -> etree.Element:
    """Crea un elemento cac:{tag} vacío."""
    return etree.SubElement(parent, f'{{{_CAC}}}{tag}')


def _amt(parent: etree.Element, tag: str, value: Decimal) -> etree.Element:
    """Crea un cbc:{tag} con valor Decimal, currencyID='PEN'."""
    el = _cbc(parent, tag, _fmt(value))
    el.set('currencyID', 'PEN')
    return el


def _d(value) -> Decimal:
    """Convierte cualquier valor numérico a Decimal con 2 decimales."""
    if value is None:
        return Decimal('0.00')
    return Decimal(str(value)).quantize(Decimal('0.01'), ROUND_HALF_UP)


def _fmt(value) -> str:
    """Formatea un Decimal a string con 2 decimales."""
    return str(_d(value))

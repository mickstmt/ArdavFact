"""Tests de generación XML UBL 2.1 para SUNAT.

Verifica:
  - Estructura correcta de Factura (01) con IGV
  - Estructura correcta de Boleta (03) con IGV
  - Estructura correcta de Nota de Crédito (07)
  - nombre_archivo con formato correcto
  - Campos críticos: TaxExemptionReasonCode, TaxScheme/ID, TaxAmount
"""
import pytest
from decimal import Decimal
from datetime import datetime
from lxml import etree

from app.services import sunat_xml_service


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures de comprobantes mock (no requieren BD)
# ─────────────────────────────────────────────────────────────────────────────

class MockCliente:
    def __init__(self, tipo='RUC', numero='20123456789', nombre_completo='EMPRESA SAC'):
        self.tipo_documento = tipo
        self.numero_documento = numero
        self._nombre_completo = nombre_completo
        self.razon_social = nombre_completo if tipo == 'RUC' else None
        self.nombres = nombre_completo if tipo != 'RUC' else None
        self.apellido_paterno = ''
        self.apellido_materno = ''
        self.direccion = None

    @property
    def nombre_completo(self):
        return self._nombre_completo

    @property
    def codigo_tipo_documento_sunat(self):
        return {'DNI': '1', 'CE': '4', 'RUC': '6'}.get(self.tipo_documento, '0')


class MockItem:
    def __init__(self, nombre='Producto Test', sku='SKU-001',
                 cantidad=Decimal('2.00'),
                 precio_con_igv=Decimal('118.00'),
                 precio_sin_igv=Decimal('100.00'),
                 igv_unitario=Decimal('18.00'),
                 subtotal_sin_igv=Decimal('200.00'),
                 igv_total=Decimal('36.00'),
                 subtotal_con_igv=Decimal('236.00'),
                 tipo_afectacion='10',
                 unidad='NIU'):
        self.producto_nombre = nombre
        self.producto_sku = sku
        self.cantidad = cantidad
        self.precio_unitario_con_igv = precio_con_igv
        self.precio_unitario_sin_igv = precio_sin_igv
        self.igv_unitario = igv_unitario
        self.subtotal_sin_igv = subtotal_sin_igv
        self.igv_total = igv_total
        self.subtotal_con_igv = subtotal_con_igv
        self.tipo_afectacion_igv = tipo_afectacion
        self.unidad_medida = unidad


class MockComprobante:
    def __init__(self, tipo='01', serie='F001', correlativo='1',
                 cliente=None, items=None, costo_envio=Decimal('0.00')):
        self.tipo_documento_sunat = tipo
        self.tipo_comprobante = {
            '01': 'FACTURA', '03': 'BOLETA',
            '07': 'NOTA_CREDITO', '08': 'NOTA_DEBITO',
        }[tipo]
        self.serie = serie
        self.correlativo = correlativo
        self.numero_completo = f'{serie}-{correlativo.zfill(8)}'
        self.fecha_emision = datetime(2026, 2, 25, 14, 30, 0)
        self.fecha_vencimiento = None
        self.numero_orden = '#1234'
        self.cliente = cliente or MockCliente()
        self.items = items or [MockItem()]
        self.costo_envio = costo_envio
        self.total_operaciones_gravadas = Decimal('200.00')
        self.total_operaciones_exoneradas = Decimal('0.00')
        self.total_operaciones_inafectas = Decimal('0.00')
        self.total_igv = Decimal('36.00')
        self.total = Decimal('236.00')
        self.comprobante_ref = None
        self.motivo_codigo = None
        self.motivo_descripcion = None

    @property
    def numero_sunat(self):
        return f'{self.serie}-{self.correlativo.zfill(8)}'

    @property
    def es_nota(self):
        return self.tipo_comprobante in ('NOTA_CREDITO', 'NOTA_DEBITO')


class MockComprobanteRef(MockComprobante):
    """Comprobante de referencia para pruebas de NC/ND."""
    def __init__(self):
        super().__init__('01', 'F001', '1')


# ─────────────────────────────────────────────────────────────────────────────
# Helpers XML
# ─────────────────────────────────────────────────────────────────────────────

_CAC = 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2'
_CBC = 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2'


def _parse(xml_bytes: bytes) -> etree.Element:
    return etree.fromstring(xml_bytes)


def _xpath(root, path: str) -> list:
    ns = {'cac': _CAC, 'cbc': _CBC}
    return root.xpath(path, namespaces=ns)


def _text(root, path: str) -> str:
    results = _xpath(root, path)
    if results:
        el = results[0]
        return el.text if hasattr(el, 'text') else str(el)
    return ''


# ─────────────────────────────────────────────────────────────────────────────
# Tests: nombre_archivo
# ─────────────────────────────────────────────────────────────────────────────

def test_nombre_archivo_factura(app):
    with app.app_context():
        comp = MockComprobante('01', 'F001', '1')
        nombre = sunat_xml_service.nombre_archivo(comp)
        assert nombre == '20605555790-01-F001-00000001'


def test_nombre_archivo_boleta(app):
    with app.app_context():
        comp = MockComprobante('03', 'B001', '5')
        nombre = sunat_xml_service.nombre_archivo(comp)
        assert nombre == '20605555790-03-B001-00000005'


def test_nombre_archivo_nc(app):
    with app.app_context():
        comp = MockComprobante('07', 'FC01', '1')
        nombre = sunat_xml_service.nombre_archivo(comp)
        assert nombre == '20605555790-07-FC01-00000001'


# ─────────────────────────────────────────────────────────────────────────────
# Tests: Factura (tipo 01)
# ─────────────────────────────────────────────────────────────────────────────

def test_factura_xml_bien_formado(app):
    with app.app_context():
        comp = MockComprobante('01', 'F001', '1')
        xml = sunat_xml_service.generar_xml(comp)
        assert isinstance(xml, bytes)
        root = _parse(xml)
        assert root is not None


def test_factura_ubl_version_21(app):
    with app.app_context():
        comp = MockComprobante('01', 'F001', '1')
        root = _parse(sunat_xml_service.generar_xml(comp))
        assert _text(root, '//cbc:UBLVersionID') == '2.1'


def test_factura_id_correcto(app):
    with app.app_context():
        comp = MockComprobante('01', 'F001', '1')
        root = _parse(sunat_xml_service.generar_xml(comp))
        assert _text(root, '//cbc:ID[1]') == 'F001-00000001'


def test_factura_invoice_type_code_01(app):
    with app.app_context():
        comp = MockComprobante('01', 'F001', '1')
        root = _parse(sunat_xml_service.generar_xml(comp))
        assert _text(root, '//cbc:InvoiceTypeCode') == '01'


def test_factura_currency_pen(app):
    with app.app_context():
        comp = MockComprobante('01', 'F001', '1')
        root = _parse(sunat_xml_service.generar_xml(comp))
        assert _text(root, '//cbc:DocumentCurrencyCode') == 'PEN'


def test_factura_tiene_due_date(app):
    """Las facturas deben tener DueDate (30 días por defecto)."""
    with app.app_context():
        comp = MockComprobante('01', 'F001', '1')
        root = _parse(sunat_xml_service.generar_xml(comp))
        due_dates = _xpath(root, '//cbc:DueDate')
        assert len(due_dates) > 0, 'Factura debe tener DueDate'


def test_factura_igv_tax_code_1000(app):
    """TaxScheme/ID para IGV debe ser '1000'."""
    with app.app_context():
        comp = MockComprobante('01', 'F001', '1')
        root = _parse(sunat_xml_service.generar_xml(comp))
        tax_ids = _xpath(root, '//cac:TaxScheme/cbc:ID/text()')
        assert '1000' in tax_ids, f"Esperaba '1000' en TaxScheme IDs: {tax_ids}"


def test_factura_igv_tax_type_vat(app):
    """TaxTypeCode para IGV debe ser 'VAT'."""
    with app.app_context():
        comp = MockComprobante('01', 'F001', '1')
        root = _parse(sunat_xml_service.generar_xml(comp))
        tax_types = _xpath(root, '//cac:TaxScheme/cbc:TaxTypeCode/text()')
        assert 'VAT' in tax_types, f"Esperaba 'VAT' en TaxTypeCodes: {tax_types}"


def test_factura_exemption_reason_10(app):
    """TaxExemptionReasonCode para gravado debe ser '10'."""
    with app.app_context():
        comp = MockComprobante('01', 'F001', '1')
        root = _parse(sunat_xml_service.generar_xml(comp))
        reasons = _xpath(root, '//cbc:TaxExemptionReasonCode/text()')
        assert '10' in reasons, f"Esperaba '10': {reasons}"


def test_factura_line_tax_amount_36(app):
    """IGV en línea = 36.00 (2 uds × S/ 18.00)."""
    with app.app_context():
        comp = MockComprobante('01', 'F001', '1')
        root = _parse(sunat_xml_service.generar_xml(comp))
        line_tax = _xpath(root, '//cac:InvoiceLine/cac:TaxTotal/cbc:TaxAmount/text()')
        assert '36.00' in line_tax, f"Esperaba '36.00': {line_tax}"


def test_factura_line_extension_200(app):
    """LineExtensionAmount = subtotal sin IGV = 200.00."""
    with app.app_context():
        comp = MockComprobante('01', 'F001', '1')
        root = _parse(sunat_xml_service.generar_xml(comp))
        line_ext = _xpath(root, '//cac:InvoiceLine/cbc:LineExtensionAmount/text()')
        assert '200.00' in line_ext, f"Esperaba '200.00': {line_ext}"


def test_factura_pricing_ref_precio_con_igv(app):
    """PricingReference debe tener precio con IGV = 118.00."""
    with app.app_context():
        comp = MockComprobante('01', 'F001', '1')
        root = _parse(sunat_xml_service.generar_xml(comp))
        precios = _xpath(root, '//cac:PricingReference//cbc:PriceAmount/text()')
        assert '118.00' in precios, f"Esperaba '118.00': {precios}"


def test_factura_emisor_ruc(app):
    with app.app_context():
        comp = MockComprobante('01', 'F001', '1')
        root = _parse(sunat_xml_service.generar_xml(comp))
        supplier_ids = _xpath(root, '//cac:AccountingSupplierParty//cbc:ID/text()')
        assert '20605555790' in supplier_ids


def test_factura_receptor_ruc(app):
    with app.app_context():
        cliente = MockCliente('RUC', '20987654321', 'CLIENTE SAC')
        comp = MockComprobante('01', 'F001', '1', cliente=cliente)
        root = _parse(sunat_xml_service.generar_xml(comp))
        customer_ids = _xpath(root, '//cac:AccountingCustomerParty//cbc:ID/text()')
        assert '20987654321' in customer_ids


def test_factura_payable_amount_236(app):
    """PayableAmount = total con IGV = 236.00."""
    with app.app_context():
        comp = MockComprobante('01', 'F001', '1')
        root = _parse(sunat_xml_service.generar_xml(comp))
        payable = _text(root, '//cac:LegalMonetaryTotal/cbc:PayableAmount')
        assert payable == '236.00'


# ─────────────────────────────────────────────────────────────────────────────
# Tests: Boleta (tipo 03)
# ─────────────────────────────────────────────────────────────────────────────

def test_boleta_invoice_type_code_03(app):
    with app.app_context():
        cliente = MockCliente('DNI', '12345678', 'Juan Perez')
        comp = MockComprobante('03', 'B001', '1', cliente=cliente)
        root = _parse(sunat_xml_service.generar_xml(comp))
        assert _text(root, '//cbc:InvoiceTypeCode') == '03'


def test_boleta_sin_due_date(app):
    """Las boletas NO deben tener DueDate."""
    with app.app_context():
        cliente = MockCliente('DNI', '12345678', 'Juan Perez')
        comp = MockComprobante('03', 'B001', '1', cliente=cliente)
        root = _parse(sunat_xml_service.generar_xml(comp))
        assert len(_xpath(root, '//cbc:DueDate')) == 0


def test_boleta_cliente_scheme_id_1_para_dni(app):
    """Para DNI, schemeID del cliente debe ser '1'."""
    with app.app_context():
        cliente = MockCliente('DNI', '12345678', 'Juan Perez')
        comp = MockComprobante('03', 'B001', '1', cliente=cliente)
        root = _parse(sunat_xml_service.generar_xml(comp))
        customer_ids = _xpath(root, '//cac:AccountingCustomerParty//cbc:ID')
        assert len(customer_ids) > 0
        assert customer_ids[0].get('schemeID') == '1'


# ─────────────────────────────────────────────────────────────────────────────
# Tests: Nota de Crédito (tipo 07)
# ─────────────────────────────────────────────────────────────────────────────

def test_nc_tiene_discrepancy_response(app):
    with app.app_context():
        comp = MockComprobante('07', 'FC01', '1')
        comp.motivo_codigo = '01'
        comp.motivo_descripcion = 'Anulación de la operación'
        comp.comprobante_ref = MockComprobanteRef()
        root = _parse(sunat_xml_service.generar_xml(comp))
        assert len(_xpath(root, '//cac:DiscrepancyResponse')) > 0


def test_nc_tiene_billing_reference(app):
    with app.app_context():
        comp = MockComprobante('07', 'FC01', '1')
        comp.motivo_codigo = '01'
        comp.comprobante_ref = MockComprobanteRef()
        root = _parse(sunat_xml_service.generar_xml(comp))
        assert len(_xpath(root, '//cac:BillingReference')) > 0


def test_nc_referencia_contiene_numero_original(app):
    with app.app_context():
        comp = MockComprobante('07', 'FC01', '1')
        comp.motivo_codigo = '01'
        comp.comprobante_ref = MockComprobanteRef()
        root = _parse(sunat_xml_service.generar_xml(comp))
        ref_id = _text(root, '//cac:BillingReference//cbc:ID')
        assert 'F001' in ref_id


def test_nc_response_code(app):
    with app.app_context():
        comp = MockComprobante('07', 'FC01', '1')
        comp.motivo_codigo = '06'
        comp.motivo_descripcion = 'Devolución total'
        comp.comprobante_ref = MockComprobanteRef()
        root = _parse(sunat_xml_service.generar_xml(comp))
        assert _text(root, '//cac:DiscrepancyResponse/cbc:ResponseCode') == '06'


# ─────────────────────────────────────────────────────────────────────────────
# Tests: tipo no soportado
# ─────────────────────────────────────────────────────────────────────────────

def test_tipo_no_soportado_lanza_error(app):
    with app.app_context():
        comp = MockComprobante('01', 'F001', '1')
        comp.tipo_documento_sunat = '99'
        with pytest.raises(ValueError, match='no soportado'):
            sunat_xml_service.generar_xml(comp)


# ─────────────────────────────────────────────────────────────────────────────
# Tests: generar_xml_b64
# ─────────────────────────────────────────────────────────────────────────────

def test_generar_xml_b64_es_base64_valido(app):
    with app.app_context():
        import base64
        comp = MockComprobante('01', 'F001', '1')
        b64 = sunat_xml_service.generar_xml_b64(comp)
        assert isinstance(b64, str)
        decoded = base64.b64decode(b64)
        assert b'<?xml' in decoded


# ─────────────────────────────────────────────────────────────────────────────
# Tests: item exonerado (tipo afectación 20)
# ─────────────────────────────────────────────────────────────────────────────

def test_item_exonerado_reason_code_20(app):
    with app.app_context():
        item_exo = MockItem(
            tipo_afectacion='20',
            igv_unitario=Decimal('0.00'),
            igv_total=Decimal('0.00'),
        )
        comp = MockComprobante('03', 'B001', '1', items=[item_exo])
        comp.total_operaciones_gravadas = Decimal('0.00')
        comp.total_operaciones_exoneradas = Decimal('200.00')
        comp.total_igv = Decimal('0.00')
        comp.total = Decimal('200.00')
        root = _parse(sunat_xml_service.generar_xml(comp))
        reasons = _xpath(root, '//cbc:TaxExemptionReasonCode/text()')
        assert '20' in reasons, f"Esperaba '20' para exonerado: {reasons}"


def test_item_inafecto_reason_code_30(app):
    with app.app_context():
        item_ina = MockItem(
            tipo_afectacion='30',
            igv_unitario=Decimal('0.00'),
            igv_total=Decimal('0.00'),
        )
        comp = MockComprobante('03', 'B001', '1', items=[item_ina])
        comp.total_operaciones_gravadas = Decimal('0.00')
        comp.total_operaciones_inafectas = Decimal('200.00')
        comp.total_igv = Decimal('0.00')
        comp.total = Decimal('200.00')
        root = _parse(sunat_xml_service.generar_xml(comp))
        reasons = _xpath(root, '//cbc:TaxExemptionReasonCode/text()')
        assert '30' in reasons, f"Esperaba '30' para inafecto: {reasons}"

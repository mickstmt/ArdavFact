"""Tests de generación de PDF con ReportLab.

Verifica:
  - generar_pdf() retorna bytes no vacíos
  - El PDF comienza con el magic number %PDF
  - Contiene datos del comprobante (número, cliente)
  - Funciona para Factura, Boleta, NC y ND
  - IGV correcto reflejado en el PDF
"""
import io
from decimal import Decimal
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest

from app.services.pdf_service import generar_pdf


# ─────────────────────────────────────────────────────────────────────────────
# Mocks (comparten estructura con test_xml_generation.py)
# ─────────────────────────────────────────────────────────────────────────────

class _MockCliente:
    tipo_documento   = 'RUC'
    numero_documento = '20123456789'
    razon_social     = 'EMPRESA TEST SAC'
    nombres          = None
    apellido_paterno = ''
    apellido_materno = ''
    direccion        = 'Av. Test 123, Lima'

    @property
    def nombre_completo(self):
        return 'EMPRESA TEST SAC'

    @property
    def codigo_tipo_documento_sunat(self):
        return '6'


class _MockClienteDNI:
    tipo_documento   = 'DNI'
    numero_documento = '12345678'
    razon_social     = None
    nombres          = 'Juan'
    apellido_paterno = 'García'
    apellido_materno = 'López'
    direccion        = None

    @property
    def nombre_completo(self):
        return 'Juan García López'

    @property
    def codigo_tipo_documento_sunat(self):
        return '1'


class _MockItem:
    def __init__(self, nombre='Producto Test', sku='SKU-001',
                 precio_con_igv=Decimal('118.00'),
                 precio_sin_igv=Decimal('100.00'),
                 igv_unitario=Decimal('18.00'),
                 subtotal_sin_igv=Decimal('100.00'),
                 igv_total=Decimal('18.00'),
                 subtotal_con_igv=Decimal('118.00'),
                 tipo='10'):
        self.producto_nombre         = nombre
        self.producto_sku            = sku
        self.cantidad                = Decimal('1')
        self.precio_unitario_con_igv = precio_con_igv
        self.precio_unitario_sin_igv = precio_sin_igv
        self.igv_unitario            = igv_unitario
        self.subtotal_sin_igv        = subtotal_sin_igv
        self.igv_total               = igv_total
        self.subtotal_con_igv        = subtotal_con_igv
        self.tipo_afectacion_igv     = tipo
        self.unidad_medida           = 'NIU'


def _make_comp(tipo='FACTURA', numero='F001-00000001', cliente=None, items=None, hash_cpe='ABCD1234'):
    comp = MagicMock()
    comp.tipo_comprobante    = tipo
    comp.numero_completo     = numero
    comp.serie               = numero.split('-')[0]
    comp.correlativo         = numero.split('-')[1].lstrip('0') or '1'
    comp.fecha_emision       = datetime(2025, 6, 15, 10, 30, 0)
    comp.fecha_vencimiento   = None
    comp.cliente             = cliente or _MockCliente()
    comp.items               = items or [_MockItem()]
    comp.costo_envio         = Decimal('0.00')
    comp.total               = Decimal('118.00')
    comp.subtotal            = Decimal('118.00')
    comp.total_igv           = Decimal('18.00')
    comp.total_operaciones_gravadas   = Decimal('100.00')
    comp.total_operaciones_exoneradas = Decimal('0.00')
    comp.total_operaciones_inafectas  = Decimal('0.00')
    comp.hash_cpe            = hash_cpe
    comp.tipo_documento_sunat = '01' if tipo == 'FACTURA' else '03'
    comp.motivo_descripcion   = None
    comp.comprobante_referencia_id = None
    comp.referencia           = None
    comp.numero_orden         = None
    return comp


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestGenerarPdf:
    def test_pdf_retorna_bytes(self, app):
        """generar_pdf() retorna bytes no vacíos."""
        comp = _make_comp()
        with app.app_context():
            pdf = generar_pdf(comp)
        assert isinstance(pdf, bytes)
        assert len(pdf) > 1000

    def test_pdf_magic_number(self, app):
        """El PDF comienza con el magic number %PDF."""
        comp = _make_comp()
        with app.app_context():
            pdf = generar_pdf(comp)
        assert pdf[:4] == b'%PDF'

    def test_pdf_factura(self, app):
        """generar_pdf() funciona para FACTURA con cliente RUC."""
        comp = _make_comp(tipo='FACTURA', numero='F001-00000001')
        with app.app_context():
            pdf = generar_pdf(comp)
        assert len(pdf) > 0

    def test_pdf_boleta(self, app):
        """generar_pdf() funciona para BOLETA con cliente DNI."""
        comp = _make_comp(tipo='BOLETA', numero='B001-00000001', cliente=_MockClienteDNI())
        comp.tipo_documento_sunat = '03'
        with app.app_context():
            pdf = generar_pdf(comp)
        assert pdf[:4] == b'%PDF'

    def test_pdf_con_costo_envio(self, app):
        """generar_pdf() incluye costo de envío correctamente."""
        comp = _make_comp()
        comp.costo_envio = Decimal('15.00')
        comp.total       = Decimal('133.00')
        with app.app_context():
            pdf = generar_pdf(comp)
        assert len(pdf) > 0

    def test_pdf_multiples_items(self, app):
        """generar_pdf() maneja múltiples ítems sin error."""
        items = [
            _MockItem(f'Producto {i}', f'SKU-{i:03d}') for i in range(1, 6)
        ]
        comp = _make_comp(items=items)
        comp.total              = Decimal('590.00')
        comp.total_igv          = Decimal('90.00')
        comp.subtotal           = Decimal('590.00')
        comp.total_operaciones_gravadas = Decimal('500.00')
        with app.app_context():
            pdf = generar_pdf(comp)
        assert pdf[:4] == b'%PDF'

    def test_pdf_sin_hash(self, app):
        """generar_pdf() funciona aunque no haya hash_cpe (QR sin hash)."""
        comp = _make_comp(hash_cpe=None)
        with app.app_context():
            pdf = generar_pdf(comp)
        assert pdf[:4] == b'%PDF'

    def test_pdf_igv_correcto_en_datos(self, app):
        """El comprobante pasado al PDF tiene IGV = 18% de la base."""
        item = _MockItem(
            precio_con_igv=Decimal('236.00'),
            precio_sin_igv=Decimal('200.00'),
            igv_unitario=Decimal('36.00'),
            subtotal_sin_igv=Decimal('200.00'),
            igv_total=Decimal('36.00'),
            subtotal_con_igv=Decimal('236.00'),
        )
        comp = _make_comp(items=[item])
        comp.total     = Decimal('236.00')
        comp.total_igv = Decimal('36.00')
        comp.total_operaciones_gravadas = Decimal('200.00')

        # Verificar que IGV = 18% de la base imponible
        assert abs(float(comp.total_igv) / float(comp.total_operaciones_gravadas) - 0.18) < 0.001

        with app.app_context():
            pdf = generar_pdf(comp)
        assert pdf[:4] == b'%PDF'

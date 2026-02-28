"""Tests del servicio de gestión de archivos (FileService).

Verifica:
  - guardar_archivos() escribe XML y CDR en disco y actualiza model.xml_path/cdr_path
  - guardar_pdf() escribe PDF en disco y actualiza model.pdf_path
  - xml_existe() / cdr_existe() / pdf_existe() detectan correctamente la presencia de archivos
  - regenerar_xml() retorna bytes de XML sin firma
  - guardar_archivos() no falla si cdr_b64 no viene en la respuesta
"""
import base64
import os
import tempfile
from decimal import Decimal
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.services.file_service import FileService


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

_XML_CONTENT = b'<?xml version="1.0"?><Invoice>TEST</Invoice>'
_CDR_CONTENT = b'<?xml version="1.0"?><CDR>TEST</CDR>'
_PDF_CONTENT = b'%PDF-1.4 fake pdf content'

_XML_B64 = base64.b64encode(_XML_CONTENT).decode()
_CDR_B64 = base64.b64encode(_CDR_CONTENT).decode()


def _make_fs(tmp_path: str) -> FileService:
    return FileService(base_path=tmp_path, empresa_ruc='20605555790')


def _make_comp(numero='F001-00000001'):
    """Comprobante mock simple para tests de FileService."""
    comp = MagicMock()
    comp.tipo_comprobante     = 'FACTURA'
    comp.tipo_documento_sunat = '01'
    comp.serie                = 'F001'
    comp.correlativo          = '1'
    comp.numero_completo      = numero
    comp.xml_path             = None
    comp.cdr_path             = None
    comp.pdf_path             = None
    comp.hash_cpe             = None

    # Para sunat_xml_service.nombre_archivo()
    cliente = MagicMock()
    cliente.numero_documento = '20605555790'
    comp.cliente = cliente
    return comp


# ─────────────────────────────────────────────────────────────────────────────
# Tests: guardar_archivos
# ─────────────────────────────────────────────────────────────────────────────

class TestGuardarArchivos:
    def test_guarda_xml(self, app, tmp_path):
        """guardar_archivos() escribe el XML en disco y actualiza xml_path."""
        fs   = _make_fs(str(tmp_path))
        comp = _make_comp()
        resultado = {
            'xml_firmado_b64': _XML_B64,
            'cdr_b64': None,
            'nombre_archivo': '20605555790-01-F001-00000001',
        }

        with app.app_context():
            fs.guardar_archivos(comp, resultado)

        assert comp.xml_path is not None
        assert os.path.isfile(comp.xml_path)
        assert open(comp.xml_path, 'rb').read() == _XML_CONTENT

    def test_guarda_cdr(self, app, tmp_path):
        """guardar_archivos() escribe el CDR en disco y actualiza cdr_path."""
        fs   = _make_fs(str(tmp_path))
        comp = _make_comp()
        resultado = {
            'xml_firmado_b64': _XML_B64,
            'cdr_b64': _CDR_B64,
            'nombre_archivo': '20605555790-01-F001-00000001',
        }

        with app.app_context():
            fs.guardar_archivos(comp, resultado)

        assert comp.cdr_path is not None
        assert os.path.isfile(comp.cdr_path)
        assert open(comp.cdr_path, 'rb').read() == _CDR_CONTENT

    def test_sin_cdr_no_falla(self, app, tmp_path):
        """guardar_archivos() no falla si cdr_b64 no viene en la respuesta."""
        fs   = _make_fs(str(tmp_path))
        comp = _make_comp()
        resultado = {
            'xml_firmado_b64': _XML_B64,
            'cdr_b64': None,
            'nombre_archivo': '20605555790-01-F001-00000001',
        }

        with app.app_context():
            fs.guardar_archivos(comp, resultado)  # no debe lanzar excepción

        assert comp.cdr_path is None

    def test_guarda_hash(self, app, tmp_path):
        """guardar_archivos() almacena el hash si viene en la respuesta."""
        fs   = _make_fs(str(tmp_path))
        comp = _make_comp()
        comp.hash_cpe = None
        resultado = {
            'xml_firmado_b64': _XML_B64,
            'cdr_b64': None,
            'nombre_archivo': '20605555790-01-F001-00000001',
            'hash': 'ABC123XYZ',
        }

        with app.app_context():
            fs.guardar_archivos(comp, resultado)

        assert comp.hash_cpe == 'ABC123XYZ'

    def test_prefijo_R_en_cdr(self, app, tmp_path):
        """El CDR se guarda con prefijo 'R-' en el nombre de archivo."""
        fs   = _make_fs(str(tmp_path))
        comp = _make_comp()
        nombre = '20605555790-01-F001-00000001'
        resultado = {
            'xml_firmado_b64': _XML_B64,
            'cdr_b64': _CDR_B64,
            'nombre_archivo': nombre,
        }

        with app.app_context():
            fs.guardar_archivos(comp, resultado)

        assert comp.cdr_path.endswith(f'R-{nombre}.xml')


# ─────────────────────────────────────────────────────────────────────────────
# Tests: guardar_pdf
# ─────────────────────────────────────────────────────────────────────────────

class TestGuardarPdf:
    def test_guarda_pdf(self, app, tmp_path):
        """guardar_pdf() escribe el PDF y actualiza pdf_path."""
        fs   = _make_fs(str(tmp_path))
        comp = _make_comp()

        with app.app_context():
            ruta = fs.guardar_pdf(comp, _PDF_CONTENT)

        assert os.path.isfile(ruta)
        assert open(ruta, 'rb').read() == _PDF_CONTENT
        assert comp.pdf_path == ruta


# ─────────────────────────────────────────────────────────────────────────────
# Tests: verificación de existencia
# ─────────────────────────────────────────────────────────────────────────────

class TestExistencia:
    def test_xml_no_existe_si_ruta_nula(self, app, tmp_path):
        fs   = _make_fs(str(tmp_path))
        comp = _make_comp()
        comp.xml_path = None
        assert fs.xml_existe(comp) is False

    def test_xml_no_existe_si_archivo_borrado(self, app, tmp_path):
        fs   = _make_fs(str(tmp_path))
        comp = _make_comp()
        comp.xml_path = str(tmp_path / 'archivo_inexistente.xml')
        assert fs.xml_existe(comp) is False

    def test_xml_existe_si_archivo_en_disco(self, app, tmp_path):
        fs   = _make_fs(str(tmp_path))
        comp = _make_comp()

        with app.app_context():
            resultado = {
                'xml_firmado_b64': _XML_B64,
                'cdr_b64': None,
                'nombre_archivo': '20605555790-01-F001-00000001',
            }
            fs.guardar_archivos(comp, resultado)

        assert fs.xml_existe(comp) is True

    def test_cdr_no_existe_si_no_guardado(self, app, tmp_path):
        fs   = _make_fs(str(tmp_path))
        comp = _make_comp()
        comp.cdr_path = None
        assert fs.cdr_existe(comp) is False

    def test_pdf_no_existe_si_no_guardado(self, app, tmp_path):
        fs   = _make_fs(str(tmp_path))
        comp = _make_comp()
        comp.pdf_path = None
        assert fs.pdf_existe(comp) is False


# ─────────────────────────────────────────────────────────────────────────────
# Tests: regenerar_xml
# ─────────────────────────────────────────────────────────────────────────────

class TestRegenerarXml:
    def test_regenerar_xml_retorna_bytes(self, app, tmp_path):
        """regenerar_xml() retorna bytes de XML sin firma."""
        from tests.test_xml_generation import MockComprobante, MockCliente, MockItem

        fs   = _make_fs(str(tmp_path))
        comp = MockComprobante(
            tipo='01', serie='F001', correlativo='9',
            cliente=MockCliente(tipo='RUC', numero='20123456789'),
            items=[MockItem()],
        )

        with app.app_context():
            xml_bytes = fs.regenerar_xml(comp)

        assert isinstance(xml_bytes, bytes)
        assert b'Invoice' in xml_bytes or b'Invoice' in xml_bytes
        assert len(xml_bytes) > 100

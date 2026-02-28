"""Tests de integración MiPSE con mocks HTTP.

Verifica:
  - test_token_refresh:             obtener_token() parsea la respuesta correctamente
  - test_firmar_xml_success:        firmar_xml() extrae xml_firmado de la respuesta
  - test_enviar_success:            enviar_comprobante() normaliza la respuesta y retorna CDR
  - test_duplicate_handling:        mensaje "ya existe" levanta MiPSEDuplicadoError
  - test_consultar_estado_recovery: procesar_comprobante recupera CDR vía consultar_estado
"""
import base64
import json
from decimal import Decimal
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest
import requests

from app.services.mipse_service import (
    obtener_token,
    firmar_xml,
    enviar_comprobante,
    consultar_estado,
    procesar_comprobante,
    MiPSEError,
    MiPSEDuplicadoError,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _mock_response(status_code: int, body: dict) -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.content = json.dumps(body).encode()
    resp.json.return_value = body
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
    return resp


_XML_FIRMADO_B64 = base64.b64encode(b'<xml_firmado>mock</xml_firmado>').decode()
_CDR_B64         = base64.b64encode(b'<CDR_mock/>').decode()


# ─────────────────────────────────────────────────────────────────────────────
# Comprobante mock (sin BD)
# ─────────────────────────────────────────────────────────────────────────────

class _MockCliente:
    tipo_documento    = 'RUC'
    numero_documento  = '20123456789'
    razon_social      = 'EMPRESA SAC'
    nombres           = None
    apellido_paterno  = ''
    apellido_materno  = ''
    direccion         = None

    @property
    def nombre_completo(self):
        return 'EMPRESA SAC'

    @property
    def codigo_tipo_documento_sunat(self):
        return '6'


class _MockItem:
    producto_nombre          = 'Producto Test'
    producto_sku             = 'SKU-001'
    cantidad                 = Decimal('1')
    precio_unitario_con_igv  = Decimal('118.00')
    precio_unitario_sin_igv  = Decimal('100.00')
    igv_unitario             = Decimal('18.00')
    subtotal_sin_igv         = Decimal('100.00')
    igv_total                = Decimal('18.00')
    subtotal_con_igv         = Decimal('118.00')
    tipo_afectacion_igv      = '10'
    unidad_medida            = 'NIU'


class _MockComprobante:
    tipo_documento_sunat         = '01'
    tipo_comprobante             = 'FACTURA'
    serie                        = 'F001'
    correlativo                  = '1'
    numero_completo              = 'F001-00000001'
    fecha_emision                = datetime(2025, 1, 15, 10, 0, 0)
    fecha_vencimiento            = None
    numero_orden                 = None
    costo_envio                  = Decimal('0.00')
    total                        = Decimal('118.00')
    total_igv                    = Decimal('18.00')
    total_operaciones_gravadas   = Decimal('100.00')
    total_operaciones_exoneradas = Decimal('0.00')
    total_operaciones_inafectas  = Decimal('0.00')
    subtotal                     = Decimal('118.00')
    motivo_codigo                = None
    motivo_descripcion           = None
    comprobante_referencia_id    = None
    referencia                   = None
    hash_cpe                     = None
    estado                       = 'PENDIENTE'
    codigo_sunat                 = None
    mensaje_sunat                = None
    fecha_envio_sunat            = None
    cliente                      = _MockCliente()
    items                        = [_MockItem()]


# ─────────────────────────────────────────────────────────────────────────────
# Tests: obtener_token
# ─────────────────────────────────────────────────────────────────────────────

class TestObtenerToken:
    def test_token_refresh(self, app):
        """obtener_token() extrae el token del campo 'token'."""
        with app.app_context():
            with patch('requests.post', return_value=_mock_response(200, {'token': 'jwt-abc-123'})):
                assert obtener_token() == 'jwt-abc-123'

    def test_token_campo_access_token(self, app):
        """obtener_token() acepta 'access_token' como nombre alternativo."""
        with app.app_context():
            with patch('requests.post', return_value=_mock_response(200, {'access_token': 'jwt-xyz'})):
                assert obtener_token() == 'jwt-xyz'

    def test_token_acceso(self, app):
        """obtener_token() acepta 'token_acceso' (formato real MiPSE)."""
        with app.app_context():
            with patch('requests.post', return_value=_mock_response(200, {'success': True, 'token_acceso': 'jwt-acceso-123', 'expira_en': 600})):
                assert obtener_token() == 'jwt-acceso-123'

    def test_token_error_red(self, app):
        """obtener_token() levanta MiPSEError si hay error de red."""
        with app.app_context():
            with patch('requests.post', side_effect=requests.ConnectionError('timeout')):
                with pytest.raises(MiPSEError, match='Error obteniendo token'):
                    obtener_token()

    def test_token_sin_campo(self, app):
        """obtener_token() levanta MiPSEError si la respuesta no trae token."""
        with app.app_context():
            with patch('requests.post', return_value=_mock_response(200, {'status': 'ok'})):
                with pytest.raises(MiPSEError, match='Token no encontrado'):
                    obtener_token()


# ─────────────────────────────────────────────────────────────────────────────
# Tests: firmar_xml
# ─────────────────────────────────────────────────────────────────────────────

class TestFirmarXml:
    def test_firmar_xml_success(self, app):
        """firmar_xml() retorna el XML firmado en base64."""
        with app.app_context():
            with patch('requests.post', return_value=_mock_response(200, {'xml_firmado': _XML_FIRMADO_B64})):
                resultado = firmar_xml('20605555790-01-F001-00000001', 'xml_b64', 'token-test')
        assert resultado == _XML_FIRMADO_B64

    def test_firmar_campo_xmlFirmado(self, app):
        """firmar_xml() acepta campo 'xmlFirmado' (camelCase)."""
        with app.app_context():
            with patch('requests.post', return_value=_mock_response(200, {'xmlFirmado': _XML_FIRMADO_B64})):
                resultado = firmar_xml('nombre', 'xml', 'token')
        assert resultado == _XML_FIRMADO_B64

    def test_firmar_xml_error_red(self, app):
        """firmar_xml() levanta MiPSEError ante error de red."""
        with app.app_context():
            with patch('requests.post', side_effect=requests.Timeout()):
                with pytest.raises(MiPSEError, match='Error firmando'):
                    firmar_xml('nombre', 'xml', 'token')

    def test_firmar_xml_sin_campo(self, app):
        """firmar_xml() levanta MiPSEError si la respuesta no trae xml_firmado."""
        with app.app_context():
            with patch('requests.post', return_value=_mock_response(200, {'status': 'ok'})):
                with pytest.raises(MiPSEError, match='XML firmado no encontrado'):
                    firmar_xml('nombre', 'xml', 'token')


# ─────────────────────────────────────────────────────────────────────────────
# Tests: enviar_comprobante
# ─────────────────────────────────────────────────────────────────────────────

class TestEnviarComprobante:
    def test_enviar_success(self, app):
        """enviar_comprobante() retorna dict normalizado con CDR."""
        body = {
            'estadoSunat': 'ACEPTADO',
            'codigoRespuesta': '0',
            'descripcion': 'Aceptado',
            'cdr': _CDR_B64,
        }
        with app.app_context():
            with patch('requests.post', return_value=_mock_response(200, body)):
                resultado = enviar_comprobante('nombre', _XML_FIRMADO_B64, 'token')

        assert resultado['estado_sunat'] == 'ACEPTADO'
        assert resultado['codigo'] == '0'
        assert resultado['cdr'] == _CDR_B64

    def test_duplicate_handling_ya_existe(self, app):
        """Mensaje 'ya existe' en HTTP 400 levanta MiPSEDuplicadoError."""
        body = {'mensaje': 'El comprobante ya existe en SUNAT'}
        with app.app_context():
            with patch('requests.post', return_value=_mock_response(400, body)):
                with pytest.raises(MiPSEDuplicadoError):
                    enviar_comprobante('nombre', _XML_FIRMADO_B64, 'token')

    def test_duplicate_handling_registrado(self, app):
        """Mensaje 'registrado' en HTTP 409 levanta MiPSEDuplicadoError."""
        body = {'message': 'Comprobante ya registrado'}
        with app.app_context():
            with patch('requests.post', return_value=_mock_response(409, body)):
                with pytest.raises(MiPSEDuplicadoError):
                    enviar_comprobante('nombre', _XML_FIRMADO_B64, 'token')

    def test_enviar_error_red(self, app):
        """Error de red en enviar levanta MiPSEError."""
        with app.app_context():
            with patch('requests.post', side_effect=requests.ConnectionError()):
                with pytest.raises(MiPSEError, match='Error enviando'):
                    enviar_comprobante('nombre', _XML_FIRMADO_B64, 'token')


# ─────────────────────────────────────────────────────────────────────────────
# Tests: consultar_estado
# ─────────────────────────────────────────────────────────────────────────────

class TestConsultarEstado:
    def test_consultar_estado_ok(self, app):
        """consultar_estado() normaliza la respuesta correctamente."""
        body = {'data': {'estadoSunat': 'ACEPTADO', 'codigo': '0', 'descripcion': 'ok', 'cdr': _CDR_B64}}
        with app.app_context():
            with patch('requests.get', return_value=_mock_response(200, body)):
                resultado = consultar_estado('nombre', 'token')

        assert resultado['estado_sunat'] == 'ACEPTADO'
        assert resultado['cdr'] == _CDR_B64

    def test_consultar_error_red(self, app):
        """Error de red en consultar levanta MiPSEError."""
        with app.app_context():
            with patch('requests.get', side_effect=requests.ConnectionError()):
                with pytest.raises(MiPSEError, match='Error consultando'):
                    consultar_estado('nombre', 'token')


# ─────────────────────────────────────────────────────────────────────────────
# Tests: procesar_comprobante (orquestación completa)
# ─────────────────────────────────────────────────────────────────────────────

class TestProcesarComprobante:
    _XML_PATCH   = 'app.services.sunat_xml_service.generar_xml_b64'
    _NOMBRE_PATCH = 'app.services.sunat_xml_service.nombre_archivo'

    def test_procesar_exito_aceptado(self, app):
        """procesar_comprobante() actualiza estado a ACEPTADO y retorna CDR."""
        comp = _MockComprobante()
        comp.estado = 'PENDIENTE'

        token_resp = _mock_response(200, {'token': 'tok'})
        firma_resp = _mock_response(200, {'xml_firmado': _XML_FIRMADO_B64})
        envio_resp = _mock_response(200, {
            'estadoSunat': 'ACEPTADO', 'codigoRespuesta': '0',
            'descripcion': 'Aceptado por SUNAT', 'cdr': _CDR_B64,
        })

        with app.app_context():
            with patch(self._NOMBRE_PATCH, return_value='20605555790-01-F001-00000001'):
                with patch(self._XML_PATCH, return_value='xml_b64_mock'):
                    with patch('requests.post', side_effect=[token_resp, firma_resp, envio_resp]):
                        resultado = procesar_comprobante(comp)

        assert resultado['success'] is True
        assert comp.estado == 'ACEPTADO'
        assert resultado['cdr_b64'] == _CDR_B64

    def test_consultar_estado_recovery(self, app):
        """Si enviar falla con duplicado, procesar usa consultar_estado para recuperar CDR."""
        comp = _MockComprobante()
        comp.estado = 'PENDIENTE'

        token_resp     = _mock_response(200, {'token': 'tok'})
        firma_resp     = _mock_response(200, {'xml_firmado': _XML_FIRMADO_B64})
        duplicado_resp = _mock_response(400, {'mensaje': 'ya existe en SUNAT'})
        consulta_resp  = _mock_response(200, {
            'estadoSunat': 'ACEPTADO', 'codigoRespuesta': '0',
            'descripcion': 'Recuperado', 'cdr': _CDR_B64,
        })

        with app.app_context():
            with patch(self._NOMBRE_PATCH, return_value='20605555790-01-F001-00000001'):
                with patch(self._XML_PATCH, return_value='xml_b64_mock'):
                    with patch('requests.post', side_effect=[token_resp, firma_resp, duplicado_resp]):
                        with patch('requests.get', return_value=consulta_resp):
                            resultado = procesar_comprobante(comp)

        assert resultado['success'] is True
        assert comp.estado == 'ACEPTADO'

    def test_procesar_estado_rechazado(self, app):
        """procesar_comprobante() actualiza estado a RECHAZADO cuando SUNAT rechaza."""
        comp = _MockComprobante()
        comp.estado = 'PENDIENTE'

        token_resp = _mock_response(200, {'token': 'tok'})
        firma_resp = _mock_response(200, {'xml_firmado': _XML_FIRMADO_B64})
        envio_resp = _mock_response(200, {
            'estadoSunat': 'RECHAZADO', 'codigoRespuesta': '2800',
            'descripcion': 'El RUC del emisor no existe', 'cdr': '',
        })

        with app.app_context():
            with patch(self._NOMBRE_PATCH, return_value='20605555790-01-F001-00000001'):
                with patch(self._XML_PATCH, return_value='xml_b64_mock'):
                    with patch('requests.post', side_effect=[token_resp, firma_resp, envio_resp]):
                        resultado = procesar_comprobante(comp)

        assert resultado['success'] is True  # el proceso terminó, pero SUNAT rechazó
        assert comp.estado == 'RECHAZADO'

    def test_procesar_error_red(self, app):
        """Si hay error de red total, procesar retorna success=False y mantiene PENDIENTE."""
        comp = _MockComprobante()
        comp.estado = 'PENDIENTE'

        with app.app_context():
            with patch(self._NOMBRE_PATCH, return_value='20605555790-01-F001-00000001'):
                with patch(self._XML_PATCH, side_effect=requests.ConnectionError('sin red')):
                    resultado = procesar_comprobante(comp)

        assert resultado['success'] is False
        assert comp.estado == 'PENDIENTE'

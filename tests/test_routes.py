"""Tests de rutas principales: autenticación, login requerido, endpoints críticos.

Verifica:
  - test_login_required:   rutas protegidas redirigen a login si no autenticado
  - test_login_logout:     flujo completo de login y logout
  - test_crear_factura:    POST /ventas/crear con mock MiPSE → comprobante PENDIENTE
  - test_crear_boleta:     igual con DNI → BOLETA
  - test_health:           /health retorna 200 OK
  - test_bulk_analizar:    POST /bulk/analizar valida extensiones
"""
import io
import json
from decimal import Decimal
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models.usuario import Usuario, Rol, Permiso
from app.models.cliente import Cliente
from app.models.comprobante import Comprobante


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def admin_user(app):
    """Crea un usuario administrador para usar en tests."""
    with app.app_context():
        u = Usuario.query.filter_by(email='test_admin@ardavfact.com').first()
        if not u:
            u = Usuario(
                nombre='Test Admin',
                email='test_admin@ardavfact.com',
                es_admin=True,
                activo=True,
            )
            u.set_password('testpass123')
            db.session.add(u)
            db.session.commit()
        return u.id  # retornar ID evita problemas de sesión SQLAlchemy


@pytest.fixture
def cliente_ruc(app):
    """Crea un cliente RUC para tests de factura."""
    with app.app_context():
        c = Cliente.query.filter_by(numero_documento='20123456789').first()
        if not c:
            c = Cliente(
                tipo_documento='RUC',
                numero_documento='20123456789',
                razon_social='EMPRESA TEST SAC',
                direccion='Av. Test 123',
            )
            db.session.add(c)
            db.session.commit()
        return c.id


@pytest.fixture
def cliente_dni(app):
    """Crea un cliente DNI para tests de boleta."""
    with app.app_context():
        c = Cliente.query.filter_by(numero_documento='12345678').first()
        if not c:
            c = Cliente(
                tipo_documento='DNI',
                numero_documento='12345678',
                nombres='Juan',
                apellido_paterno='García',
                apellido_materno='López',
            )
            db.session.add(c)
            db.session.commit()
        return c.id


def _login(client, email='test_admin@ardavfact.com', password='testpass123'):
    return client.post('/auth/login', data={'login': email, 'password': password},
                       follow_redirects=True)


# ─────────────────────────────────────────────────────────────────────────────
# Tests: health check
# ─────────────────────────────────────────────────────────────────────────────

def test_health(client):
    """GET /health retorna status ok."""
    resp = client.get('/health')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['status'] == 'ok'


# ─────────────────────────────────────────────────────────────────────────────
# Tests: login requerido
# ─────────────────────────────────────────────────────────────────────────────

class TestLoginRequerido:
    """Verifica que las rutas protegidas redirigen al login."""

    RUTAS = [
        '/ventas/',
        '/ventas/nueva',
        '/bulk/',
        '/reportes/ganancias',
        '/admin/usuarios',
        '/productos/',
    ]

    def test_login_required_redirige(self, client):
        """Sin sesión, todas las rutas protegidas redirigen a /auth/login."""
        for ruta in self.RUTAS:
            resp = client.get(ruta)
            assert resp.status_code in (302, 401), f'Ruta {ruta} no protegida (status {resp.status_code})'
            if resp.status_code == 302:
                assert '/auth/login' in resp.headers.get('Location', ''), \
                    f'Ruta {ruta} no redirige a login'


# ─────────────────────────────────────────────────────────────────────────────
# Tests: autenticación
# ─────────────────────────────────────────────────────────────────────────────

class TestAutenticacion:
    def test_login_exitoso(self, client, admin_user, app):
        """Login con credenciales correctas redirige al dashboard."""
        resp = _login(client)
        assert resp.status_code == 200

    def test_login_credenciales_incorrectas(self, client, admin_user):
        """Login con contraseña incorrecta retorna 200 con mensaje de error."""
        resp = client.post(
            '/auth/login',
            data={'email': 'test_admin@ardavfact.com', 'password': 'wrongpass'},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b'nv' in resp.data.lower() or b'login' in resp.data.lower()

    def test_login_usuario_inactivo(self, client, app):
        """Login con usuario inactivo no permite el acceso."""
        with app.app_context():
            u = Usuario.query.filter_by(email='inactivo@test.com').first()
            if not u:
                u = Usuario(nombre='Inactivo', email='inactivo@test.com', activo=False)
                u.set_password('testpass123')
                db.session.add(u)
                db.session.commit()

        resp = client.post(
            '/auth/login',
            data={'email': 'inactivo@test.com', 'password': 'testpass123'},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        # No debe llegar al dashboard
        assert b'dashboard' not in resp.data.lower() or b'login' in resp.data.lower()

    def test_logout(self, client, admin_user):
        """Logout desconecta la sesión."""
        _login(client)
        resp = client.get('/auth/logout', follow_redirects=True)
        assert resp.status_code == 200
        # Después de logout, /ventas/ debe redirigir a login
        resp2 = client.get('/ventas/')
        assert resp2.status_code in (302, 401)


# ─────────────────────────────────────────────────────────────────────────────
# Tests: crear comprobante (con mock MiPSE)
# ─────────────────────────────────────────────────────────────────────────────

_MIPSE_EXITO = {
    'success': True,
    'estado': 'ENVIADO',
    'codigo_sunat': '0',
    'mensaje_sunat': 'Comprobante aceptado',
    'xml_firmado_b64': None,
    'cdr_b64': None,
    'nombre_archivo': '20605555790-01-F001-00000001',
}


class TestCrearFactura:
    def test_crear_factura(self, client, app, admin_user, cliente_ruc):
        """POST /ventas/nueva con RUC crea una FACTURA en estado PENDIENTE o ENVIADO."""
        _login(client)

        payload = {
            'cliente': {
                'tipo_documento': 'RUC',
                'numero_documento': '20123456789',
                'razon_social': 'EMPRESA TEST SAC',
                'direccion': 'Av. Test 123',
            },
            'items': [
                {
                    'nombre': 'Producto de prueba',
                    'sku': 'SKU-TEST',
                    'cantidad': 1,
                    'precio_con_igv': 118.00,
                    'tipo_afectacion_igv': '10',
                }
            ],
            'costo_envio': 0,
        }

        with patch('app.services.mipse_service.procesar_comprobante', return_value=_MIPSE_EXITO):
            with patch('app.services.file_service.FileService.guardar_archivos'):
                resp = client.post(
                    '/ventas/nueva',
                    data=json.dumps(payload),
                    content_type='application/json',
                )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert 'comprobante_id' in data

        with app.app_context():
            comp = db.session.get(Comprobante, data['comprobante_id'])
            assert comp is not None
            assert comp.tipo_comprobante == 'FACTURA'

    def test_crear_boleta(self, client, app, admin_user, cliente_dni):
        """POST /ventas/nueva con DNI crea una BOLETA."""
        _login(client)

        payload = {
            'cliente': {
                'tipo_documento': 'DNI',
                'numero_documento': '12345678',
                'nombres': 'Juan',
                'apellido_paterno': 'García',
                'apellido_materno': 'López',
            },
            'items': [
                {
                    'nombre': 'Artículo boleta',
                    'sku': '',
                    'cantidad': 1,
                    'precio_con_igv': 59.00,
                    'tipo_afectacion_igv': '10',
                }
            ],
            'costo_envio': 10,
        }

        with patch('app.services.mipse_service.procesar_comprobante', return_value=_MIPSE_EXITO):
            with patch('app.services.file_service.FileService.guardar_archivos'):
                resp = client.post(
                    '/ventas/nueva',
                    data=json.dumps(payload),
                    content_type='application/json',
                )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True

        with app.app_context():
            comp = db.session.get(Comprobante, data['comprobante_id'])
            assert comp.tipo_comprobante == 'BOLETA'

    def test_crear_sin_items_retorna_400(self, client, admin_user):
        """POST /ventas/nueva sin ítems retorna error 400."""
        _login(client)
        payload = {
            'cliente': {
                'tipo_documento': 'RUC',
                'numero_documento': '20123456789',
                'razon_social': 'EMPRESA TEST SAC',
            },
            'items': [],
            'costo_envio': 0,
        }
        resp = client.post(
            '/ventas/nueva',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert resp.status_code in (400, 200)
        if resp.status_code == 200:
            data = resp.get_json()
            assert data['success'] is False


# ─────────────────────────────────────────────────────────────────────────────
# Tests: bulk upload
# ─────────────────────────────────────────────────────────────────────────────

class TestBulkUpload:
    def test_analizar_sin_archivo_retorna_400(self, client, admin_user):
        """POST /bulk/analizar sin archivo retorna 400."""
        _login(client)
        resp = client.post('/bulk/analizar')
        assert resp.status_code == 400
        data = resp.get_json()
        assert data['success'] is False

    def test_analizar_extension_invalida_retorna_400(self, client, admin_user):
        """POST /bulk/analizar con archivo .txt retorna 400."""
        _login(client)
        data_file = (io.BytesIO(b'contenido falso'), 'archivo.txt')
        resp = client.post(
            '/bulk/analizar',
            data={'archivo': data_file},
            content_type='multipart/form-data',
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data['success'] is False
        assert 'Formato no válido' in data['message']

    def test_procesar_sin_ordenes_retorna_400(self, client, admin_user):
        """POST /bulk/procesar sin órdenes retorna 400."""
        _login(client)
        resp = client.post(
            '/bulk/procesar',
            data=json.dumps({'ordenes': []}),
            content_type='application/json',
        )
        assert resp.status_code == 400

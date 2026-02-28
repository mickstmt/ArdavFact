"""Tests de modelos SQLAlchemy — Fase 8: Parte 2 del Sprint Final.

Cubre:
- Propiedades y helpers de Cliente
- Propiedades y helpers de Comprobante
- Propiedades de ComprobanteItem
- Constraint único serie+correlativo
"""
import pytest
from app.models.cliente import Cliente
from app.models.comprobante import Comprobante, ComprobanteItem
from app.extensions import db as _db

# Contador para generar números de documento únicos entre tests
_doc_counter = iter(range(10000000, 99999999))


def _next_dni() -> str:
    return str(next(_doc_counter))

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures de modelos base
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def cliente_dni(db):
    """Cliente persona natural con DNI."""
    c = Cliente(
        tipo_documento='DNI',
        numero_documento=_next_dni(),
        nombres='Juan',
        apellido_paterno='García',
        apellido_materno='López',
    )
    db.session.add(c)
    db.session.flush()
    return c


@pytest.fixture
def cliente_ruc(db):
    """Cliente empresa con RUC."""
    c = Cliente(
        tipo_documento='RUC',
        numero_documento='20' + str(next(_doc_counter))[:9],
        razon_social='Empresa Demo S.A.C.',
        nombre_comercial='Demo SAC',
    )
    db.session.add(c)
    db.session.flush()
    return c


@pytest.fixture
def comprobante_base(db, cliente_dni):
    """Comprobante BOLETA mínimo en estado BORRADOR."""
    comp = Comprobante(
        tipo_comprobante='BOLETA',
        tipo_documento_sunat='03',
        serie='B001',
        correlativo='1',
        numero_completo='B001-00000001',
        cliente_id=cliente_dni.id,
        total=100,
        estado='BORRADOR',
    )
    db.session.add(comp)
    db.session.flush()
    return comp


# ─────────────────────────────────────────────────────────────────────────────
# Tests: Cliente.nombre_completo
# ─────────────────────────────────────────────────────────────────────────────

def test_cliente_nombre_completo_persona_natural(cliente_dni):
    """nombre_completo debe concatenar nombres + apellidos para DNI."""
    assert cliente_dni.nombre_completo == 'Juan García López'


def test_cliente_nombre_completo_persona_juridica(cliente_ruc):
    """nombre_completo debe retornar razon_social para RUC."""
    assert cliente_ruc.nombre_completo == 'Empresa Demo S.A.C.'


def test_cliente_nombre_completo_sin_segundo_apellido(db):
    """Apellido materno vacío no deja espacio doble."""
    c = Cliente(
        tipo_documento='DNI',
        numero_documento=_next_dni(),
        nombres='Ana',
        apellido_paterno='Torres',
        apellido_materno=None,
    )
    db.session.add(c)
    db.session.flush()
    assert c.nombre_completo == 'Ana Torres'


# ─────────────────────────────────────────────────────────────────────────────
# Tests: Cliente.codigo_tipo_documento_sunat
# ─────────────────────────────────────────────────────────────────────────────

def test_codigo_tipo_documento_dni(cliente_dni):
    """DNI → catálogo 06 = '1'."""
    assert cliente_dni.codigo_tipo_documento_sunat == '1'


def test_codigo_tipo_documento_ruc(cliente_ruc):
    """RUC → catálogo 06 = '6'."""
    assert cliente_ruc.codigo_tipo_documento_sunat == '6'


def test_codigo_tipo_documento_ce(db):
    """Carné de extranjería → catálogo 06 = '4'."""
    c = Cliente(
        tipo_documento='CE',
        numero_documento='CE' + str(next(_doc_counter)),
    )
    db.session.add(c)
    db.session.flush()
    assert c.codigo_tipo_documento_sunat == '4'


def test_codigo_tipo_documento_pasaporte(db):
    """Pasaporte → catálogo 06 = '7'."""
    c = Cliente(
        tipo_documento='PASAPORTE',
        numero_documento='PA' + str(next(_doc_counter)),
    )
    db.session.add(c)
    db.session.flush()
    assert c.codigo_tipo_documento_sunat == '7'


# ─────────────────────────────────────────────────────────────────────────────
# Tests: Comprobante.numero_sunat
# ─────────────────────────────────────────────────────────────────────────────

def test_comprobante_numero_sunat_con_zfill(comprobante_base):
    """numero_sunat debe rellenar el correlativo hasta 8 dígitos con ceros."""
    assert comprobante_base.numero_sunat == 'B001-00000001'


def test_comprobante_numero_sunat_correlativo_grande(db, cliente_dni):
    comp = Comprobante(
        tipo_comprobante='FACTURA',
        tipo_documento_sunat='01',
        serie='F001',
        correlativo='12345',
        numero_completo='F001-00012345',
        cliente_id=cliente_dni.id,
        total=0,
        estado='BORRADOR',
    )
    db.session.add(comp)
    db.session.flush()
    assert comp.numero_sunat == 'F001-00012345'


# ─────────────────────────────────────────────────────────────────────────────
# Tests: Comprobante.es_nota
# ─────────────────────────────────────────────────────────────────────────────

def test_comprobante_es_nota_nc(db, cliente_dni):
    nc = Comprobante(
        tipo_comprobante='NOTA_CREDITO',
        tipo_documento_sunat='07',
        serie='BC01',
        correlativo='1',
        numero_completo='BC01-00000001',
        cliente_id=cliente_dni.id,
        total=0,
        estado='BORRADOR',
    )
    db.session.add(nc)
    db.session.flush()
    assert nc.es_nota is True


def test_comprobante_es_nota_nd(db, cliente_dni):
    nd = Comprobante(
        tipo_comprobante='NOTA_DEBITO',
        tipo_documento_sunat='08',
        serie='BD01',
        correlativo='1',
        numero_completo='BD01-00000001',
        cliente_id=cliente_dni.id,
        total=0,
        estado='BORRADOR',
    )
    db.session.add(nd)
    db.session.flush()
    assert nd.es_nota is True


def test_comprobante_no_es_nota_boleta(comprobante_base):
    assert comprobante_base.es_nota is False


# ─────────────────────────────────────────────────────────────────────────────
# Tests: Comprobante.esta_enviado
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('estado,esperado', [
    ('ENVIADO',   True),
    ('ACEPTADO',  True),
    ('PENDIENTE', False),
    ('BORRADOR',  False),
    ('RECHAZADO', False),
])
def test_comprobante_esta_enviado(db, cliente_dni, estado, esperado):
    """esta_enviado == True solo para ENVIADO y ACEPTADO."""
    comp = Comprobante(
        tipo_comprobante='BOLETA',
        tipo_documento_sunat='03',
        serie='B001',
        correlativo=estado,          # correlativo único por test
        numero_completo=f'B001-{estado}',
        cliente_id=cliente_dni.id,
        total=0,
        estado=estado,
    )
    db.session.add(comp)
    db.session.flush()
    assert comp.esta_enviado is esperado


# ─────────────────────────────────────────────────────────────────────────────
# Tests: Constraint únic serie+correlativo
# ─────────────────────────────────────────────────────────────────────────────

def test_comprobante_unique_constraint(db, cliente_dni):
    """No se pueden crear dos comprobantes con la misma serie+correlativo."""
    from sqlalchemy.exc import IntegrityError

    comp1 = Comprobante(
        tipo_comprobante='BOLETA',
        tipo_documento_sunat='03',
        serie='B001',
        correlativo='9999',
        numero_completo='B001-00009999',
        cliente_id=cliente_dni.id,
        total=50,
        estado='BORRADOR',
    )
    db.session.add(comp1)
    db.session.commit()

    comp2 = Comprobante(
        tipo_comprobante='BOLETA',
        tipo_documento_sunat='03',
        serie='B001',
        correlativo='9999',         # mismo que comp1 → violación
        numero_completo='B001-00009999',
        cliente_id=cliente_dni.id,
        total=50,
        estado='BORRADOR',
    )
    db.session.add(comp2)
    with pytest.raises(IntegrityError):
        db.session.flush()
    db.session.rollback()


# ─────────────────────────────────────────────────────────────────────────────
# Tests: ComprobanteItem.__repr__
# ─────────────────────────────────────────────────────────────────────────────

def test_comprobante_item_repr(db, comprobante_base):
    """__repr__ debe incluir SKU y cantidad."""
    item = ComprobanteItem(
        comprobante_id=comprobante_base.id,
        producto_nombre='Polo Básico Negro',
        producto_sku='POLO-NEG-M',
        cantidad=2,
        precio_unitario_con_igv=59,
        precio_unitario_sin_igv=50,
        igv_unitario=9,
        subtotal_sin_igv=100,
        igv_total=18,
        subtotal_con_igv=118,
    )
    db.session.add(item)
    db.session.flush()
    r = repr(item)
    assert 'POLO-NEG-M' in r
    assert '2' in r

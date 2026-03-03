"""Servicio de búsqueda y creación de clientes.

Prioridad de búsqueda:
1. BD local (más rápido, datos ya validados)
2. ApisPeru (consulta externa DNI/RUC)
"""
import requests
import structlog
from flask import current_app
from app.extensions import db
from app.models.cliente import Cliente

logger = structlog.get_logger()


# ─────────────────────────────────────────────────────────────────────────────
# Búsqueda local
# ─────────────────────────────────────────────────────────────────────────────

def buscar_cliente_local(numero_documento: str) -> Cliente | None:
    """Busca cliente en la BD por número de documento."""
    return Cliente.query.filter_by(
        numero_documento=numero_documento.strip()
    ).first()


def buscar_clientes_por_nombre(termino: str, limite: int = 10) -> list[Cliente]:
    """Búsqueda por nombre/razón social (ILIKE)."""
    t = f'%{termino.strip()}%'
    return (
        Cliente.query
        .filter(
            db.or_(
                Cliente.razon_social.ilike(t),
                Cliente.nombres.ilike(t),
                Cliente.numero_documento.ilike(t),
            )
        )
        .limit(limite)
        .all()
    )


# ─────────────────────────────────────────────────────────────────────────────
# Consulta ApisPeru
# ─────────────────────────────────────────────────────────────────────────────

def _headers_apisperu() -> dict:
    token = current_app.config.get('APISPERU_TOKEN', '')
    return {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}


def consultar_ruc_apisperu(ruc: str) -> dict | None:
    """Consulta datos de un RUC en ApisPeru.
    Retorna dict con datos o None si falla.
    """
    try:
        url = f'https://dniruc.apisperu.com/api/v1/ruc/{ruc}'
        r = requests.get(url, headers=_headers_apisperu(), timeout=8)
        if r.status_code == 200:
            data = r.json()
            if data.get('razonSocial'):
                return data
    except Exception as e:
        logger.warning('apisperu_ruc_error', ruc=ruc, error=str(e))
    return None


def consultar_dni_apisperu(dni: str) -> dict | None:
    """Consulta datos de un DNI en ApisPeru."""
    try:
        url = f'https://dniruc.apisperu.com/api/v1/dni/{dni}'
        r = requests.get(url, headers=_headers_apisperu(), timeout=8)
        if r.status_code == 200:
            data = r.json()
            if data.get('apellidoPaterno') or data.get('nombres'):
                return data
    except Exception as e:
        logger.warning('apisperu_dni_error', dni=dni, error=str(e))
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Búsqueda completa (local → ApisPeru)
# ─────────────────────────────────────────────────────────────────────────────

def buscar_o_crear_cliente(numero_documento: str, tipo_documento: str | None = None) -> dict:
    """
    Busca el cliente localmente. Si no existe, consulta ApisPeru.
    NO guarda automáticamente — el guardado ocurre al emitir el comprobante.

    Retorna:
        {
            'encontrado': bool,
            'fuente': 'local' | 'apisperu' | None,
            'cliente': {...datos...} | None,
            'error': str | None,
        }
    """
    numero = numero_documento.strip()

    # 1. Buscar en BD local
    cliente = buscar_cliente_local(numero)
    if cliente:
        return {
            'encontrado': True,
            'fuente': 'local',
            'cliente': _cliente_to_dict(cliente),
            'error': None,
        }

    # 2. Determinar tipo si no se pasó
    if not tipo_documento:
        tipo_documento = _detectar_tipo(numero)

    # 3. Consultar ApisPeru
    data_api = None
    if tipo_documento == 'RUC' and len(numero) == 11:
        data_api = consultar_ruc_apisperu(numero)
    elif tipo_documento == 'DNI' and len(numero) == 8:
        data_api = consultar_dni_apisperu(numero)

    if not data_api:
        return {'encontrado': False, 'fuente': None, 'cliente': None, 'error': 'No encontrado'}

    # 4. Mapear respuesta ApisPeru a dict cliente
    cliente_dict = _mapear_apisperu(numero, tipo_documento, data_api)
    return {'encontrado': True, 'fuente': 'apisperu', 'cliente': cliente_dict, 'error': None}


def guardar_cliente_desde_dict(datos: dict) -> Cliente:
    """Guarda o actualiza un cliente desde un dict de datos.
    Llamar al confirmar la emisión del comprobante.
    """
    cliente = buscar_cliente_local(datos['numero_documento'])
    if not cliente:
        cliente = Cliente(numero_documento=datos['numero_documento'])
        db.session.add(cliente)

    for campo, valor in datos.items():
        if hasattr(cliente, campo):
            try:
                setattr(cliente, campo, valor)
            except AttributeError:
                pass  # ignorar @property de solo lectura (ej. nombre_completo)

    db.session.flush()
    return cliente


# ─────────────────────────────────────────────────────────────────────────────
# Helpers internos
# ─────────────────────────────────────────────────────────────────────────────

def _detectar_tipo(numero: str) -> str:
    if len(numero) == 11 and numero.startswith('2'):
        return 'RUC'
    if len(numero) == 11:
        return 'RUC'
    if len(numero) == 8:
        return 'DNI'
    return 'CE'


def _mapear_apisperu(numero: str, tipo: str, data: dict) -> dict:
    if tipo == 'RUC':
        razon = (data.get('razonSocial') or '').strip()
        return {
            'tipo_documento': 'RUC',
            'numero_documento': numero,
            'razon_social': razon,
            'nombre_comercial': (data.get('nombreComercial') or '').strip() or None,
            'direccion': (data.get('direccion') or '').strip() or None,
            'nombre_completo': razon,
        }
    else:
        nombres = (data.get('nombres') or '').strip()
        ap = (data.get('apellidoPaterno') or '').strip()
        am = (data.get('apellidoMaterno') or '').strip()
        nombre_completo = ' '.join(p for p in [nombres, ap, am] if p)
        return {
            'tipo_documento': 'DNI',
            'numero_documento': numero,
            'nombres': nombres,
            'apellido_paterno': ap,
            'apellido_materno': am,
            'nombre_completo': nombre_completo,
        }


def _cliente_to_dict(cliente: Cliente) -> dict:
    return {
        'id': cliente.id,
        'tipo_documento': cliente.tipo_documento,
        'numero_documento': cliente.numero_documento,
        'razon_social': cliente.razon_social,
        'nombre_comercial': cliente.nombre_comercial,
        'nombres': cliente.nombres,
        'apellido_paterno': cliente.apellido_paterno,
        'apellido_materno': cliente.apellido_materno,
        'nombre_completo': cliente.nombre_completo,
        'direccion': cliente.direccion,
        'email': cliente.email,
        'telefono': cliente.telefono,
    }

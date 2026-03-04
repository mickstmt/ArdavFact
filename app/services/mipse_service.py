"""Integración con MiPSE (Proveedor de Servicios Electrónicos).

Flujo completo de un comprobante:
  1. obtener_token()          → Bearer token de acceso
  2. firmar_xml(nombre, b64)  → XML firmado digitalmente
  3. enviar_comprobante(...)  → Envío a SUNAT, recibe CDR
  4. consultar_estado(nombre) → Consulta CDR si falla el envío

Manejo de duplicados (lección aprendida de iziFact):
  Si enviar falla con "ya existe"/"registrado", se llama a consultar_estado
  para recuperar el CDR existente sin crear duplicados en SUNAT.
"""
import base64
import structlog
import requests
from datetime import datetime
from flask import current_app
from app.extensions import db
from app.services import sunat_xml_service

logger = structlog.get_logger()


# ─────────────────────────────────────────────────────────────────────────────
# Excepciones
# ─────────────────────────────────────────────────────────────────────────────

class MiPSEError(Exception):
    """Error en la comunicación o respuesta de MiPSE."""


class MiPSEDuplicadoError(MiPSEError):
    """El comprobante ya fue enviado a SUNAT anteriormente."""


# ─────────────────────────────────────────────────────────────────────────────
# API interna — llamadas HTTP a MiPSE
# ─────────────────────────────────────────────────────────────────────────────

def _base_url() -> str:
    cfg = current_app.config
    return f"{cfg.get('MIPSE_URL', 'https://api.mipse.pe')}/pro/{cfg.get('MIPSE_SYSTEM', 'produccion')}"


def _auth_payload() -> dict:
    cfg = current_app.config
    return {
        'usuario':   cfg.get('MIPSE_USUARIO', ''),
        'contraseña': cfg.get('MIPSE_PASSWORD', ''),
    }


def _headers(token: str | None = None) -> dict:
    """Headers comunes para todas las peticiones a MiPSE."""
    h = {'Accept': 'application/json', 'Content-Type': 'application/json'}
    if token:
        h['Authorization'] = f'Bearer {token}'
    return h


def obtener_token() -> str:
    """Obtiene un Bearer token de MiPSE.

    Returns:
        str: Token JWT de acceso.

    Raises:
        MiPSEError: Si la autenticación falla.
    """
    url = f'{_base_url()}/auth/cpe/token'
    try:
        r = requests.post(url, json=_auth_payload(), headers=_headers(), timeout=15)
        r.raise_for_status()
        data = r.json()
        token = data.get('token_acceso') or data.get('token') or data.get('access_token')
        if not token:
            raise MiPSEError(f'Token no encontrado en respuesta: {data}')
        logger.info('mipse_token_ok')
        return token
    except requests.RequestException as e:
        logger.error('mipse_token_error', error=str(e))
        raise MiPSEError(f'Error obteniendo token MiPSE: {e}')


def firmar_xml(nombre: str, xml_b64: str, token: str) -> str:
    """Envía XML a MiPSE para firma digital.

    Args:
        nombre:  Nombre del archivo (ej: 20605555790-01-F001-00000001)
        xml_b64: XML en base64
        token:   Bearer token

    Returns:
        str: XML firmado en base64.
    """
    url = f'{_base_url()}/cpe/generar'
    payload = {'tipo_integracion': 0, 'nombre_archivo': nombre, 'contenido_archivo': xml_b64}
    try:
        r = requests.post(url, json=payload, headers=_headers(token), timeout=60)
        r.raise_for_status()
        data = r.json()
        # MiPSE devuelve el XML firmado en el campo 'xml'
        firmado = data.get('xml') or data.get('xml_firmado') or data.get('xmlFirmado')
        if not firmado:
            raise MiPSEError(f'XML firmado no encontrado en respuesta: {data}')
        logger.info('mipse_firma_ok', nombre=nombre)
        return firmado
    except requests.RequestException as e:
        logger.error('mipse_firma_error', nombre=nombre, error=str(e))
        raise MiPSEError(f'Error firmando XML en MiPSE: {e}')


def enviar_comprobante(nombre: str, xml_firmado_b64: str, token: str) -> dict:
    """Envía comprobante firmado a SUNAT vía MiPSE.

    Returns:
        dict: Resultado con campos cdr, estado_sunat, codigo, descripcion, etc.

    Raises:
        MiPSEDuplicadoError: Si el comprobante ya fue registrado antes.
        MiPSEError: En otros errores de envío.
    """
    url = f'{_base_url()}/cpe/enviar'
    payload = {'nombre_xml_firmado': nombre, 'contenido_xml_firmado': xml_firmado_b64}
    try:
        r = requests.post(url, json=payload, headers=_headers(token), timeout=120)
        data = r.json() if r.content else {}

        # Manejo de duplicados: código 0111 o mensaje "ya existe"
        msg_lower = str(data.get('mensaje', '') or data.get('message', '')).lower()
        if r.status_code in (400, 409) or any(
            kw in msg_lower for kw in ('ya existe', 'registrado', 'duplicado', '0111')
        ):
            logger.warning('mipse_duplicado', nombre=nombre, response=data)
            raise MiPSEDuplicadoError(nombre)

        if not r.ok:
            logger.error('mipse_envio_http_error', nombre=nombre, status=r.status_code, data=data)
            raise MiPSEError(f'MiPSE enviar HTTP {r.status_code}: {data}')

        # MiPSE puede responder 2xx pero con success=false (ej. SUNAT no responde)
        if data.get('success') is False:
            msg = data.get('mensaje') or data.get('message') or data.get('errores') or 'MiPSE reportó error sin CDR'
            logger.warning('mipse_envio_sunat_error', nombre=nombre, status=r.status_code, data=data)
            raise MiPSEError(f'MiPSE no pudo entregar a SUNAT: {msg}')

        logger.info('mipse_envio_ok', nombre=nombre)
        normalizado = _normalizar_respuesta(data)
        logger.info('mipse_envio_normalizado', nombre=nombre, estado_sunat=normalizado.get('estado_sunat'), codigo=normalizado.get('codigo'), tiene_cdr=bool(normalizado.get('cdr')))
        return normalizado

    except MiPSEDuplicadoError:
        raise
    except requests.RequestException as e:
        logger.error('mipse_envio_error', nombre=nombre, error=str(e))
        raise MiPSEError(f'Error enviando comprobante a MiPSE: {e}')


def consultar_estado(nombre: str, token: str) -> dict:
    """Consulta el estado de un comprobante enviado previamente.

    Returns:
        dict: Resultado normalizado con cdr, estado, etc.
    """
    url = f'{_base_url()}/cpe/consultar/{nombre}'
    try:
        r = requests.get(url, headers=_headers(token), timeout=30)
        r.raise_for_status()
        data = r.json()
        logger.info('mipse_consulta_ok', nombre=nombre, data=data)
        normalizado = _normalizar_respuesta(data)
        logger.info('mipse_consulta_normalizado', nombre=nombre, estado_sunat=normalizado.get('estado_sunat'), tiene_cdr=bool(normalizado.get('cdr')))
        return normalizado
    except requests.RequestException as e:
        logger.error('mipse_consulta_error', nombre=nombre, error=str(e))
        raise MiPSEError(f'Error consultando estado en MiPSE: {e}')


# ─────────────────────────────────────────────────────────────────────────────
# Función de alto nivel
# ─────────────────────────────────────────────────────────────────────────────

def procesar_comprobante(comprobante) -> dict:
    """Genera XML, firma y envía un comprobante a SUNAT vía MiPSE.

    Actualiza el estado del comprobante en BD según el resultado.
    NO hace commit — el caller es responsable del commit.

    Returns:
        dict: {
            'success': bool,
            'estado': 'ENVIADO' | 'ACEPTADO' | 'RECHAZADO',
            'codigo_sunat': str,
            'mensaje_sunat': str,
            'xml_firmado_b64': str | None,
            'cdr_b64': str | None,
            'nombre_archivo': str,
        }
    """
    nombre = sunat_xml_service.nombre_archivo(comprobante)
    log = logger.bind(comprobante=comprobante.numero_completo, nombre=nombre)

    try:
        # 1. Generar XML
        log.info('mipse_proceso_inicio')
        xml_b64 = sunat_xml_service.generar_xml_b64(comprobante)

        # 2. Obtener token
        token = obtener_token()

        # 3. Firmar
        xml_firmado_b64 = firmar_xml(nombre, xml_b64, token)

        # 4. Enviar (con manejo de duplicados y recuperación por error SUNAT)
        resultado = None
        try:
            resultado = enviar_comprobante(nombre, xml_firmado_b64, token)
        except MiPSEDuplicadoError:
            log.warning('mipse_duplicado_recuperando')
            resultado = consultar_estado(nombre, token)
        except MiPSEError as envio_err:
            # Si MiPSE reporta que SUNAT no respondió, intentar consultar por si
            # el comprobante SÍ fue registrado (race condition o timeout interno)
            msg_err = str(envio_err).lower()
            if any(kw in msg_err for kw in ('no pudo entregar', 'no responde', 'sunat')):
                log.warning('mipse_envio_fallido_consultando', error=str(envio_err))
                try:
                    resultado = consultar_estado(nombre, token)
                    log.info('mipse_recuperado_por_consulta', estado_sunat=resultado.get('estado_sunat'))
                except MiPSEError:
                    raise envio_err  # consultar también falló, propagar el error original
            else:
                raise

        # 5. Actualizar comprobante
        estado_sunat  = resultado.get('estado_sunat', '').upper()
        codigo_sunat  = str(resultado.get('codigo', '') or '')
        mensaje_sunat = resultado.get('descripcion') or resultado.get('mensaje') or ''

        # MiPSE a veces embebe el código en el mensaje ("3300 - La sumatoria...")
        # Si codigo_sunat está vacío, intentar extraerlo del mensaje
        if not codigo_sunat and mensaje_sunat:
            import re
            m = re.match(r'^(\d{3,4})\s*[-–]', mensaje_sunat)
            if m:
                codigo_sunat = m.group(1)
                log.info('mipse_codigo_extraido_de_mensaje', codigo=codigo_sunat)

        # El código SUNAT es la fuente de verdad:
        # 3xxx/4xxx = RECHAZADO | 0xxx/2xxx = ACEPTADO | sin código → estado MiPSE
        if codigo_sunat.startswith(('3', '4')):
            comprobante.estado = 'RECHAZADO'
        elif codigo_sunat.startswith(('0', '2')) or estado_sunat in ('ACEPTADO', 'ACEPTADO CON OBSERVACIONES'):
            comprobante.estado = 'ACEPTADO'
        elif estado_sunat == 'RECHAZADO':
            comprobante.estado = 'RECHAZADO'
        else:
            comprobante.estado = 'ENVIADO'

        comprobante.codigo_sunat  = codigo_sunat
        comprobante.mensaje_sunat = mensaje_sunat
        comprobante.fecha_envio_sunat = datetime.utcnow()

        log.info('mipse_proceso_ok', estado=comprobante.estado, codigo=codigo_sunat)
        return {
            'success': True,
            'estado': comprobante.estado,
            'codigo_sunat': codigo_sunat,
            'mensaje_sunat': mensaje_sunat,
            'xml_firmado_b64': xml_firmado_b64,
            'cdr_b64': resultado.get('cdr'),
            'nombre_archivo': nombre,
        }

    except (MiPSEError, Exception) as e:
        comprobante.estado = 'PENDIENTE'  # mantener pendiente para reintento
        comprobante.mensaje_sunat = str(e)
        log.error('mipse_proceso_error', error=str(e))
        return {
            'success': False,
            'estado': 'PENDIENTE',
            'codigo_sunat': '',
            'mensaje_sunat': str(e),
            'xml_firmado_b64': None,
            'cdr_b64': None,
            'nombre_archivo': nombre,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers internos
# ─────────────────────────────────────────────────────────────────────────────

def _normalizar_respuesta(data: dict) -> dict:
    """Normaliza la respuesta de MiPSE a una estructura consistente.

    MiPSE devuelve:
      - enviar/consultar: {'estado': 200, 'mensaje': '...aceptada...', 'cdr': 'base64'}
      - estado puede ser número (200) o string
    """
    inner = data.get('data') or data


    # MiPSE usa estado numérico (200=ok) o string
    estado_raw = inner.get('estado') or inner.get('estadoSunat') or inner.get('estado_sunat') or ''
    if estado_raw == 200 or str(estado_raw) == '200':
        estado_sunat = 'ACEPTADO'
    else:
        estado_sunat = str(estado_raw).upper() if estado_raw else ''

    mensaje = inner.get('mensaje') or inner.get('message') or inner.get('descripcion') or ''

    return {
        'estado_sunat':   estado_sunat,
        'codigo':         inner.get('codigoRespuesta') or inner.get('codigo') or inner.get('code') or '',
        'descripcion':    mensaje,
        'cdr':            inner.get('cdr') or inner.get('cdrBase64') or '',
        'xml_firmado':    inner.get('xml') or inner.get('xmlFirmado') or inner.get('xml_firmado') or '',
        'hash':           inner.get('codigo_hash') or inner.get('hash') or inner.get('hashCpe') or '',
        'nombre_archivo': inner.get('nombreArchivo') or inner.get('nombre_archivo') or inner.get('nombre') or '',
    }

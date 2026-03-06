"""Servicio de carga masiva desde Excel de Falabella.

Formato del Excel de Falabella (0-indexed, header=0 — primera fila son cabeceras):
  B(1)  = SKU
  D(3)  = Fecha del pedido
  E(4)  = N° Orden (agrupador)
  J(9)  = Nombre del cliente
  L(11) = DNI/RUC del cliente
  AJ(35)= Precio total del ítem (con IGV)
  AL(37)= Costo de envío (con IGV)
  AO(40)= Descripción del ítem
"""
import logging

import pandas as pd

from app.services.bulk_service import (
    _analizar_orden,
    procesar_ordenes,       # re-exportar para que routes lo consuma directamente
    _normalizar_doc,
)

logger = logging.getLogger(__name__)

# ── Índices de columna (0-based, header=0) ──────────────────────────────────
_COL_SKU    = 1   # B
_COL_FECHA  = 3   # D
_COL_ORDEN  = 4   # E
_COL_NOMBRE = 9   # J
_COL_DOC    = 11  # L
_COL_PRECIO = 35  # AJ — Precio total del ítem (con IGV); qty implícita = 1
_COL_ENVIO  = 37  # AL — Costo de envío (con IGV)
_COL_DESC   = 40  # AO — Descripción del ítem


# ── API pública ──────────────────────────────────────────────────────────────

def analizar_excel(file_path: str, config: dict) -> list[dict]:
    """
    Lee el Excel de Falabella y agrupa filas por N° Orden.
    Retorna lista de dicts con status='OK'|'WARNING'|'ERROR'.
    """
    try:
        df = pd.read_excel(file_path, header=0, dtype=str)
    except Exception as exc:
        logger.error('[BULK-FAL] Error leyendo Excel: %s', exc)
        raise ValueError(f'No se pudo leer el archivo Excel: {exc}')

    ordenes: dict[str, dict] = {}

    for _, row in df.iterrows():
        numero_orden = _val(row, _COL_ORDEN)
        if not numero_orden:
            continue

        if numero_orden not in ordenes:
            ordenes[numero_orden] = {
                'numero_orden':    numero_orden,
                'nombre_cliente':  _val(row, _COL_NOMBRE),
                'numero_documento': _normalizar_doc(_val(row, _COL_DOC)),
                'fecha_str':       _val(row, _COL_FECHA),
                'costo_envio_str': _val(row, _COL_ENVIO) or '0',
                'items_raw':       [],
                'errores':         [],
                'advertencias':    [],
            }
        else:
            # El envío puede aparecer en cualquier fila del grupo
            if ordenes[numero_orden]['costo_envio_str'] in ('', '0'):
                envio_fila = _val(row, _COL_ENVIO)
                if envio_fila and envio_fila != '0':
                    ordenes[numero_orden]['costo_envio_str'] = envio_fila

        sku = _limpiar_sku(_val(row, _COL_SKU))
        desc = _val(row, _COL_DESC) or _val(row, _COL_NOMBRE)

        ordenes[numero_orden]['items_raw'].append({
            'sku':          sku,
            'descripcion':  desc,
            'precio_str':   _val(row, _COL_PRECIO) or '0',
            'cantidad_str': '1',  # AJ es precio TOTAL del ítem; cantidad implícita = 1
        })

    cache_clientes: dict = {}
    resultados = []
    for numero_orden, orden in ordenes.items():
        resultado = _analizar_orden(orden, config, cache_clientes)
        resultados.append(resultado)

    resultados.sort(key=lambda r: r['numero_orden'])
    return resultados


# ── Helpers privados ─────────────────────────────────────────────────────────

def _val(row, col_idx: int) -> str:
    """Extrae y limpia un valor de una fila de DataFrame."""
    try:
        v = row.iloc[col_idx]
        return str(v).strip() if pd.notna(v) and str(v).strip() not in ('', 'nan', 'None') else ''
    except (IndexError, KeyError):
        return ''


def _limpiar_sku(sku: str) -> str:
    """Falabella a veces exporta enteros como '1000001.0' — lo normaliza."""
    if sku.endswith('.0'):
        sku = sku[:-2]
    return sku

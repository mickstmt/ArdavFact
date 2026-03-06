"""Servicio de carga masiva desde Excel de MercadoLibre.

Formato del Excel de MercadoLibre (0-indexed, header=0 — primera fila son cabeceras):
  A(0)  = N° Orden (agrupador)
  G(6)  = Fecha del pedido
  V(21) = Costo de envío (con IGV)
  AE(30)= SKU
  AF(31)= Variante del producto (se concatena al nombre)
  AH(33)= Precio individual ítem (con IGV)
  AI(34)= Cantidad
  AQ(42)= Descripción / Nombre del producto
  AU(46)= Nombre del cliente
  AX(49)= DNI / RUC del cliente

Particularidad multi-ítem: los datos generales de la orden (cliente, envío, fecha)
sólo aparecen en la PRIMERA fila de cada grupo de orden. Las filas siguientes del
mismo N° Orden sólo aportan ítems adicionales.
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
_COL_ORDEN  = 0   # A  — N° Orden (clave de agrupación)
_COL_FECHA  = 6   # G  — Fecha del pedido
_COL_ENVIO  = 21  # V  — Costo de envío (con IGV)
_COL_SKU    = 30  # AE — SKU del producto
_COL_VAR    = 31  # AF — Variante (talla, color, etc.)
_COL_PRECIO = 33  # AH — Precio unitario del ítem (con IGV)
_COL_QTY    = 34  # AI — Cantidad
_COL_DESC   = 42  # AQ — Descripción / nombre del producto
_COL_NOMBRE = 46  # AU — Nombre del cliente
_COL_DOC    = 49  # AX — DNI / RUC del cliente


# ── API pública ──────────────────────────────────────────────────────────────

def analizar_excel(file_path: str, config: dict) -> list[dict]:
    """
    Lee el Excel de MercadoLibre y agrupa filas por N° Orden.
    Retorna lista de dicts con status='OK'|'WARNING'|'ERROR'.
    """
    try:
        df = pd.read_excel(file_path, header=0, dtype=str)
    except Exception as exc:
        logger.error('[BULK-MELI] Error leyendo Excel: %s', exc)
        raise ValueError(f'No se pudo leer el archivo Excel: {exc}')

    ordenes: dict[str, dict] = {}

    for _, row in df.iterrows():
        numero_orden = _val(row, _COL_ORDEN)
        if not numero_orden:
            continue

        if numero_orden not in ordenes:
            # Primera fila del grupo: capturar datos generales de la orden
            ordenes[numero_orden] = {
                'numero_orden':     numero_orden,
                'nombre_cliente':   _val(row, _COL_NOMBRE),
                'numero_documento': _normalizar_doc(_val(row, _COL_DOC)),
                'fecha_str':        _val(row, _COL_FECHA),
                'costo_envio_str':  _val(row, _COL_ENVIO) or '0',
                'items_raw':        [],
                'errores':          [],
                'advertencias':     [],
            }
        # Nota: filas siguientes del mismo grupo no actualizan datos de cabecera;
        # el envío sólo se lee de la primera fila (comportamiento de Meli).

        desc = _val(row, _COL_DESC)
        variante = _val(row, _COL_VAR)
        if variante:
            desc = f'{desc} - {variante}' if desc else variante

        ordenes[numero_orden]['items_raw'].append({
            'sku':          _limpiar_sku(_val(row, _COL_SKU)),
            'descripcion':  desc or _val(row, _COL_NOMBRE),
            'precio_str':   _val(row, _COL_PRECIO) or '0',
            'cantidad_str': _val(row, _COL_QTY) or '1',
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
    """Normaliza SKUs que vengan como float ('1000001.0' → '1000001')."""
    if sku.endswith('.0'):
        sku = sku[:-2]
    return sku

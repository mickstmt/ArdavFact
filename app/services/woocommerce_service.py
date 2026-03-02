"""Sincronización de productos y categorías desde WooCommerce."""
import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from woocommerce import API
from flask import current_app

from app.extensions import db
from app.models.producto import Categoria, Producto, Variacion

logger = logging.getLogger(__name__)

_IGV_FACTOR = Decimal('1.18')
_DOS_DECIMALES = Decimal('0.01')


def _get_wcapi() -> API:
    cfg = current_app.config
    return API(
        url=cfg['WOO_URL'],
        consumer_key=cfg['WOO_CONSUMER_KEY'],
        consumer_secret=cfg['WOO_CONSUMER_SECRET'],
        version='wc/v3',
        timeout=30,
    )


def _precio_sin_igv(precio_con_igv: Decimal) -> Decimal:
    return (precio_con_igv / _IGV_FACTOR).quantize(_DOS_DECIMALES, rounding=ROUND_HALF_UP)


# ─────────────────────────────────────────────────────────────────────────────
# Categorías
# ─────────────────────────────────────────────────────────────────────────────

def sincronizar_categorias() -> dict:
    """Sincroniza todas las categorías WooCommerce → DB. Retorna estadísticas.

    Usa dos pasadas para evitar FK violations:
    1. Inserta/actualiza todas las categorías con padre_id=None
    2. Actualiza padre_id en una segunda pasada cuando todos los registros existen
    """
    wcapi = _get_wcapi()
    creadas = actualizadas = errores = 0
    todas: list[dict] = []

    # Recolectar todas las categorías primero
    pagina = 1
    while True:
        resp = wcapi.get('products/categories', params={'per_page': 100, 'page': pagina})
        if resp.status_code != 200:
            logger.error('[WOO] Error obteniendo categorías: %s', resp.text)
            break
        items = resp.json()
        if not items:
            break
        todas.extend(items)
        if len(items) < 100:
            break
        pagina += 1

    # Pasada 1: insertar/actualizar sin padre_id (evita FK violations)
    for cat_data in todas:
        try:
            cat = db.session.get(Categoria, cat_data['id'])
            if cat is None:
                cat = Categoria(id=cat_data['id'])
                db.session.add(cat)
                creadas += 1
            else:
                actualizadas += 1
            cat.nombre   = cat_data['name']
            cat.slug     = cat_data['slug']
            cat.count    = cat_data['count']
            cat.padre_id = None  # temporal, se asigna en pasada 2
        except Exception as exc:
            logger.error('[WOO] Error upsert categoría %s: %s', cat_data.get('id'), exc)
            db.session.rollback()
            errores += 1

    db.session.commit()

    # Pasada 2: asignar padre_id ahora que todos los registros existen
    for cat_data in todas:
        padre_id = cat_data.get('parent') or None
        if padre_id:
            try:
                cat = db.session.get(Categoria, cat_data['id'])
                if cat:
                    cat.padre_id = padre_id
            except Exception as exc:
                logger.error('[WOO] Error asignando padre %s→%s: %s', cat_data.get('id'), padre_id, exc)
                errores += 1

    db.session.commit()

    return {'creadas': creadas, 'actualizadas': actualizadas, 'errores': errores}


# ─────────────────────────────────────────────────────────────────────────────
# Variaciones
# ─────────────────────────────────────────────────────────────────────────────

def _sincronizar_variaciones(producto: Producto) -> None:
    """Borra y recrea variaciones de un producto variable."""
    wcapi = _get_wcapi()
    pagina = 1

    ids_remotos = set()
    while True:
        resp = wcapi.get(
            f'products/{producto.id}/variations',
            params={'per_page': 100, 'page': pagina},
        )
        if resp.status_code != 200:
            logger.warning('[WOO] No se pudieron obtener variaciones de %s', producto.id)
            break

        variaciones_data = resp.json()
        if not variaciones_data:
            break

        for var_data in variaciones_data:
            ids_remotos.add(var_data['id'])
            var = db.session.get(Variacion, var_data['id'])
            if var is None:
                var = Variacion(id=var_data['id'], producto_id=producto.id)
                db.session.add(var)

            # 'price' es el precio activo en WooCommerce (incluye oferta si la hay)
            # 'regular_price' es el precio original sin descuento
            precio_raw = Decimal(str(var_data.get('price') or var_data.get('regular_price') or '0'))
            var.sku          = var_data.get('sku', '')
            var.precio       = precio_raw
            var.precio_sin_igv = _precio_sin_igv(precio_raw)
            var.stock_status = var_data.get('stock_status', 'instock')
            var.imagen_url   = (var_data.get('image') or {}).get('src')

            # Atributos como dict {"Nombre": "Valor"}
            var.atributos = {
                a['name']: a['option']
                for a in var_data.get('attributes', [])
                if a.get('name') and a.get('option')
            }

        if len(variaciones_data) < 100:
            break
        pagina += 1

    # Eliminar variaciones que ya no existen en WooCommerce
    for var in list(producto.variaciones):
        if var.id not in ids_remotos:
            db.session.delete(var)


# ─────────────────────────────────────────────────────────────────────────────
# Productos
# ─────────────────────────────────────────────────────────────────────────────

def _upsert_producto(p_data: dict) -> str:
    """Crea o actualiza un producto. Retorna 'creado' | 'actualizado'."""
    prod = db.session.get(Producto, p_data['id'])
    accion = 'actualizado'
    if prod is None:
        prod = Producto(id=p_data['id'])
        db.session.add(prod)
        accion = 'creado'

    # 'price' es el precio activo en WooCommerce (incluye oferta si la hay)
    precio_raw = Decimal(str(p_data.get('price') or p_data.get('regular_price') or '0'))
    prod.nombre               = p_data['name']
    prod.sku                  = p_data.get('sku', '')
    prod.precio               = precio_raw
    prod.precio_sin_igv       = _precio_sin_igv(precio_raw)
    prod.stock_status         = p_data.get('stock_status', 'instock')
    prod.tipo                 = p_data.get('type', 'simple')
    prod.imagen_url           = (p_data.get('images') or [{}])[0].get('src')

    # Sincronizar categorías
    cat_ids = [c['id'] for c in p_data.get('categories', [])]
    if cat_ids:
        cats = Categoria.query.filter(Categoria.id.in_(cat_ids)).all()
        prod.categorias = cats

    db.session.flush()

    if prod.tipo == 'variable':
        _sincronizar_variaciones(prod)

    return accion


def sincronizar_productos(progress_cb=None) -> dict:
    """Sincroniza todos los productos WooCommerce → DB. Retorna estadísticas.

    Args:
        progress_cb: Callable opcional(procesados, creados, actualizados, errores)
                     Se llama después de procesar cada página de 100 productos.
    """
    wcapi = _get_wcapi()
    creados = actualizados = errores = 0
    pagina = 1

    while True:
        resp = wcapi.get('products', params={'per_page': 100, 'page': pagina, 'status': 'publish'})
        if resp.status_code != 200:
            logger.error('[WOO] Error obteniendo productos (página %s): %s', pagina, resp.text)
            break

        productos_data = resp.json()
        if not productos_data:
            break

        for p_data in productos_data:
            try:
                accion = _upsert_producto(p_data)
                if accion == 'creado':
                    creados += 1
                else:
                    actualizados += 1
            except Exception as exc:
                logger.error('[WOO] Error upsert producto %s: %s', p_data.get('id'), exc, exc_info=True)
                db.session.rollback()
                errores += 1

        db.session.commit()

        if progress_cb:
            progress_cb(creados + actualizados + errores, creados, actualizados, errores)

        if len(productos_data) < 100:
            break
        pagina += 1

    return {'creados': creados, 'actualizados': actualizados, 'errores': errores}


# ─────────────────────────────────────────────────────────────────────────────
# Sync completo
# ─────────────────────────────────────────────────────────────────────────────

def sincronizar_todo(progress_cb=None) -> dict:
    """Sincroniza categorías y productos. Retorna resumen completo.

    Args:
        progress_cb: Callable opcional(fase, procesados, creados, actualizados, errores)
    """
    logger.info('[WOO] Iniciando sincronización completa')

    if progress_cb:
        progress_cb('categorias', 0, 0, 0, 0)
    stats_cats = sincronizar_categorias()

    if progress_cb:
        progress_cb('productos', 0, 0, 0, 0)

    def _prod_cb(procesados, creados, actualizados, errores):
        if progress_cb:
            progress_cb('productos', procesados, creados, actualizados, errores)

    stats_prods = sincronizar_productos(progress_cb=_prod_cb)
    logger.info('[WOO] Sincronización completa. Cats=%s | Prods=%s', stats_cats, stats_prods)
    return {
        'categorias': stats_cats,
        'productos': stats_prods,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Búsqueda por SKU (usada por bulk_service)
# ─────────────────────────────────────────────────────────────────────────────

def buscar_variacion_por_sku(sku: str) -> Optional[Variacion]:
    return Variacion.query.filter(
        Variacion.sku.ilike(sku.strip())
    ).first()


def buscar_producto_por_sku(sku: str) -> Optional[Producto]:
    return Producto.query.filter(
        Producto.sku.ilike(sku.strip())
    ).first()

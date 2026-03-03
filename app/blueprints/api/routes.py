"""Endpoints JSON internos: clientes, productos, categorías."""
from flask import request, jsonify, current_app
from flask_login import login_required
from app.extensions import db
from app.models.producto import Producto, Variacion, Categoria
from app.models.comprobante import Comprobante
from app.services.cliente_service import (
    buscar_clientes_por_nombre,
    buscar_cliente_local,
    buscar_o_crear_cliente,
)
from . import api_bp


# ─────────────────────────────────────────────────────────────────────────────
# Clientes
# ─────────────────────────────────────────────────────────────────────────────

@api_bp.route('/buscar-cliente')
@login_required
def buscar_cliente():
    """Búsqueda local de clientes por nombre o número de documento."""
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify({'success': True, 'data': []})

    clientes = buscar_clientes_por_nombre(q, limite=10)
    data = [
        {
            'id': c.id,
            'tipo_documento': c.tipo_documento,
            'numero_documento': c.numero_documento,
            'nombre_completo': c.nombre_completo,
            'direccion': c.direccion or '',
        }
        for c in clientes
    ]
    return jsonify({'success': True, 'data': data})


@api_bp.route('/consultar-documento')
@login_required
def consultar_documento():
    """Consulta un DNI o RUC: primero BD local, luego ApisPeru."""
    numero = request.args.get('numero', '').strip()
    tipo   = request.args.get('tipo', '').strip().upper() or None

    if not numero:
        return jsonify({'success': False, 'message': 'Número requerido'}), 400

    resultado = buscar_o_crear_cliente(numero, tipo)
    if not resultado['encontrado']:
        return jsonify({'success': False, 'message': 'Documento no encontrado.'}), 404

    # Determinar serie automáticamente
    cliente = resultado['cliente']
    serie, tipo_comp = _determinar_serie_tipo(cliente['tipo_documento'], current_app.config)

    return jsonify({
        'success': True,
        'fuente': resultado['fuente'],
        'cliente': cliente,
        'tipo_comprobante': tipo_comp,
        'serie': serie,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Productos y Categorías
# ─────────────────────────────────────────────────────────────────────────────

@api_bp.route('/categorias')
@login_required
def get_categorias():
    """Árbol completo de categorías con subcategorías."""
    todas = Categoria.query.order_by(Categoria.nombre).all()
    cat_dict = {}
    raices = []

    for c in todas:
        cat_data = {
            'id': c.id,
            'nombre': c.nombre,
            'count': c.count,
            'padre_id': c.padre_id or 0,
            'hijos': [],
        }
        cat_dict[c.id] = cat_data
        if c.padre_id is None:
            raices.append(cat_data)

    # Anidar subcategorías
    for cat_data in cat_dict.values():
        padre_id = cat_data['padre_id']
        if padre_id and padre_id in cat_dict:
            cat_dict[padre_id]['hijos'].append(cat_data)

    return jsonify({'success': True, 'data': raices})


@api_bp.route('/productos-por-categoria/<int:categoria_id>')
@login_required
def get_productos_por_categoria(categoria_id: int):
    """Productos de una categoría (incluyendo subcategorías). categoria_id=0 = todos."""
    if categoria_id == 0:
        productos = Producto.query.order_by(Producto.nombre).limit(100).all()
    else:
        cat = db.session.get(Categoria, categoria_id)
        if not cat:
            return jsonify({'success': False, 'message': 'Categoría no encontrada'}), 404
        ids = [cat.id] + [h.id for h in cat.hijos]
        productos = (
            Producto.query
            .filter(Producto.categorias.any(Categoria.id.in_(ids)))
            .order_by(Producto.nombre)
            .all()
        )
    return jsonify({'success': True, 'data': [_producto_dict(p) for p in productos]})


@api_bp.route('/buscar-productos')
@login_required
def buscar_productos():
    """Búsqueda de productos por nombre o SKU (incluyendo SKUs de variaciones).

    Parámetros:
        q           -- texto de búsqueda (mínimo 2 chars)
        categoria_id -- filtrar por categoría cuando no hay texto (opcional)
    """
    q           = request.args.get('q', '').strip()
    categoria_id = request.args.get('categoria_id', '0').strip()

    query = Producto.query

    if len(q) >= 2:
        t = f'%{q}%'
        query = query.filter(
            db.or_(
                Producto.nombre.ilike(t),
                Producto.sku.ilike(t),
                Producto.variaciones.any(Variacion.sku.ilike(t)),
            )
        )
    elif categoria_id and categoria_id != '0':
        # Sin texto pero con categoría: delegar al endpoint de categoría
        try:
            cat_id = int(categoria_id)
        except ValueError:
            return jsonify({'success': True, 'data': []})
        cat = db.session.get(Categoria, cat_id)
        if cat:
            ids = [cat.id] + [h.id for h in cat.hijos]
            query = query.filter(Producto.categorias.any(Categoria.id.in_(ids)))
    else:
        return jsonify({'success': True, 'data': []})

    productos = query.order_by(Producto.nombre).limit(50).all()
    return jsonify({'success': True, 'data': [_producto_dict(p) for p in productos]})


@api_bp.route('/variaciones/<int:producto_id>')
@login_required
def get_variaciones(producto_id: int):
    """Variaciones de un producto variable."""
    variaciones = Variacion.query.filter_by(producto_id=producto_id).all()
    data = [
        {
            'id': v.id,
            'sku': v.sku,
            'precio': float(v.precio),
            'precio_sin_igv': float(v.precio_sin_igv),
            'stock_status': v.stock_status,
            'atributos': v.atributos,
            'imagen_url': v.imagen_url,
        }
        for v in variaciones
    ]
    return jsonify({'success': True, 'data': data})


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _producto_dict(p: Producto) -> dict:
    d = {
        'id': p.id,
        'nombre': p.nombre,
        'sku': p.sku or '',
        'precio': float(p.precio),
        'precio_min': float(p.precio),
        'precio_max': float(p.precio),
        'precio_sin_igv': float(p.precio_sin_igv),
        'stock_status': p.stock_status,
        'tipo': p.tipo,
        'imagen_url': p.imagen_url or '',
    }
    if p.tipo == 'variable' and p.variaciones:
        precios = [float(v.precio) for v in p.variaciones if v.precio]
        if precios:
            d['precio_min'] = min(precios)
            d['precio_max'] = max(precios)
            d['precio']     = min(precios)  # precio referencial = mínimo
    return d


def _determinar_serie_tipo(tipo_documento: str, config) -> tuple[str, str]:
    """Retorna (serie, tipo_comprobante) según el tipo de documento del cliente."""
    if tipo_documento == 'RUC':
        return config.get('SERIE_FACTURA', 'F001'), 'FACTURA'
    return config.get('SERIE_BOLETA', 'B001'), 'BOLETA'

"""Panel de productos: listado y sincronización WooCommerce."""
from flask import render_template, jsonify, request, current_app
from flask_login import login_required
from app.extensions import db
from app.models.producto import Producto, Categoria
from app.services import woocommerce_service as woo_svc
from app.decorators import requiere_permiso
from . import productos_bp


@productos_bp.route('/')
@login_required
@requiere_permiso('ventas.ver')
def lista_productos():
    """Listado de productos sincronizados."""
    q = request.args.get('q', '').strip()
    categoria_id = request.args.get('categoria_id', type=int)
    page = request.args.get('page', 1, type=int)

    query = Producto.query

    if q:
        t = f'%{q}%'
        query = query.filter(
            db.or_(Producto.nombre.ilike(t), Producto.sku.ilike(t))
        )

    if categoria_id:
        query = query.filter(
            Producto.categorias.any(Categoria.id == categoria_id)
        )

    productos = query.order_by(Producto.nombre).paginate(page=page, per_page=50, error_out=False)
    categorias = Categoria.query.filter_by(padre_id=None).order_by(Categoria.nombre).all()

    total_db = Producto.query.count()

    return render_template(
        'productos/lista.html',
        productos=productos,
        categorias=categorias,
        total_db=total_db,
        q=q,
        categoria_id=categoria_id,
    )


@productos_bp.route('/sync', methods=['POST'])
@login_required
@requiere_permiso('ventas.crear')
def sync_woocommerce():
    """Dispara sincronización completa WooCommerce → BD."""
    if not current_app.config.get('WOO_URL'):
        return jsonify({'success': False, 'message': 'WooCommerce no está configurado.'}), 400

    try:
        stats = woo_svc.sincronizar_todo()
        return jsonify({
            'success': True,
            'message': (
                f"Sincronizado: "
                f"{stats['productos']['creados']} productos nuevos, "
                f"{stats['productos']['actualizados']} actualizados, "
                f"{stats['categorias']['creadas']} categorías nuevas."
            ),
            'stats': stats,
        })
    except Exception as exc:
        current_app.logger.error('[WOO] Error en sync: %s', exc, exc_info=True)
        return jsonify({'success': False, 'message': f'Error de sincronización: {exc}'}), 500

"""Panel de productos: listado y sincronización WooCommerce."""
import threading
from flask import render_template, jsonify, request, current_app
from flask_login import login_required
from app.extensions import db, limiter
from app.models.producto import Producto, Categoria
from app.services import woocommerce_service as woo_svc
from app.decorators import requiere_permiso
from . import productos_bp

# Estado global de sincronización (solo 1 worker Gunicorn → seguro)
_sync_status: dict = {
    'running': False,
    'fase': '',
    'procesados': 0,
    'creados': 0,
    'actualizados': 0,
    'errores': 0,
    'cats_creadas': 0,
    'finished': False,
    'success': None,
    'message': '',
}


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
        sync_running=_sync_status['running'],
    )


@productos_bp.route('/sync', methods=['POST'])
@login_required
@requiere_permiso('ventas.crear')
def sync_woocommerce():
    """Inicia sincronización WooCommerce en background. Retorna inmediatamente."""
    global _sync_status

    if not current_app.config.get('WOO_URL'):
        return jsonify({'success': False, 'message': 'WooCommerce no está configurado.'}), 400

    if _sync_status['running']:
        return jsonify({'success': False, 'message': 'Ya hay una sincronización en curso.'}), 409

    # Resetear estado
    _sync_status = {
        'running': True,
        'fase': 'categorias',
        'procesados': 0,
        'creados': 0,
        'actualizados': 0,
        'errores': 0,
        'cats_creadas': 0,
        'finished': False,
        'success': None,
        'message': '',
    }

    app = current_app._get_current_object()
    t = threading.Thread(target=_run_sync_background, args=(app,), daemon=True)
    t.start()

    return jsonify({'success': True, 'message': 'started'})


@productos_bp.route('/sync/status', methods=['GET'])
@login_required
@limiter.exempt
def sync_status():
    """Devuelve el estado actual de la sincronización (exento de rate limit — es polling)."""
    return jsonify(_sync_status)


def _run_sync_background(app) -> None:
    """Ejecuta la sincronización completa en un hilo background."""
    global _sync_status

    def on_progress(fase, procesados, creados, actualizados, errores):
        _sync_status.update({
            'fase': fase,
            'procesados': procesados,
            'creados': creados,
            'actualizados': actualizados,
            'errores': errores,
        })

    with app.app_context():
        try:
            stats = woo_svc.sincronizar_todo(progress_cb=on_progress)
            _sync_status.update({
                'running': False,
                'finished': True,
                'success': True,
                'fase': 'completado',
                'creados': stats['productos']['creados'],
                'actualizados': stats['productos']['actualizados'],
                'errores': stats['productos']['errores'],
                'cats_creadas': stats['categorias']['creadas'],
                'message': (
                    f"{stats['productos']['creados']} productos nuevos, "
                    f"{stats['productos']['actualizados']} actualizados"
                    + (f", {stats['productos']['errores']} errores" if stats['productos']['errores'] else '')
                    + f", {stats['categorias']['creadas']} categorías nuevas."
                ),
            })
        except Exception as exc:
            app.logger.error('[WOO] Error en sync background: %s', exc, exc_info=True)
            _sync_status.update({
                'running': False,
                'finished': True,
                'success': False,
                'fase': 'error',
                'message': str(exc),
            })

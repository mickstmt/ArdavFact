"""Decorators de autorización para ArdavFact."""
from functools import wraps
from flask import abort, flash, redirect, url_for
from flask_login import current_user


def requiere_permiso(codigo: str):
    """Verifica que el usuario tenga el permiso indicado.

    Uso:
        @requiere_permiso('ventas.crear')
        def nueva_venta(): ...
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('auth.login'))
            if not current_user.tiene_permiso(codigo):
                flash('No tienes permiso para realizar esta acción.', 'danger')
                abort(403)
            return f(*args, **kwargs)
        return decorated
    return decorator


def solo_admin(f):
    """Permite acceso solo a usuarios con es_admin=True."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if not current_user.es_admin:
            flash('Esta sección es solo para administradores.', 'danger')
            abort(403)
        return f(*args, **kwargs)
    return decorated

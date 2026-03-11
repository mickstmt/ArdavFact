"""Rutas de administración: gestión de usuarios y roles."""
from flask import render_template, request, jsonify, current_app
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models.usuario import Usuario, Rol
from app.decorators import requiere_permiso
from . import admin_bp


# ─────────────────────────────────────────────────────────────────────────────
# Listado de usuarios
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route('/usuarios')
@login_required
@requiere_permiso('usuarios.gestionar')
def usuarios():
    """Panel de gestión de usuarios."""
    todos   = Usuario.query.order_by(Usuario.fecha_creacion.desc()).all()
    roles   = Rol.query.order_by(Rol.nombre).all()
    return render_template('admin/usuarios.html', usuarios=todos, roles=roles)


# ─────────────────────────────────────────────────────────────────────────────
# Crear usuario
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route('/usuarios/crear', methods=['POST'])
@login_required
@requiere_permiso('usuarios.gestionar')
def crear_usuario():
    """Crea un nuevo usuario desde el panel admin."""
    payload  = request.get_json(force=True) or {}
    nombre   = payload.get('nombre', '').strip()
    email    = payload.get('email', '').strip().lower()
    password = payload.get('password', '').strip()
    rol_id   = payload.get('rol_id', type=int) or payload.get('rol_id')
    es_admin = bool(payload.get('es_admin', False))

    if not nombre or not email or not password:
        return jsonify({'success': False, 'message': 'Nombre, email y contraseña son obligatorios.'}), 400

    if len(password) < 8:
        return jsonify({'success': False, 'message': 'La contraseña debe tener al menos 8 caracteres.'}), 400

    if Usuario.query.filter_by(email=email).first():
        return jsonify({'success': False, 'message': f'El email "{email}" ya está en uso.'}), 409

    try:
        usuario = Usuario(nombre=nombre, email=email, es_admin=es_admin, activo=True)
        usuario.set_password(password)

        if rol_id:
            rol = db.session.get(Rol, int(rol_id))
            if rol:
                usuario.roles.append(rol)

        db.session.add(usuario)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Usuario "{nombre}" creado correctamente.',
            'usuario': _usuario_dict(usuario),
        })
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error('[ADMIN] Error creando usuario: %s', exc, exc_info=True)
        return jsonify({'success': False, 'message': f'Error interno: {exc}'}), 500


# ─────────────────────────────────────────────────────────────────────────────
# Activar / Desactivar
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route('/usuarios/<int:user_id>/toggle', methods=['POST'])
@login_required
@requiere_permiso('usuarios.gestionar')
def toggle_usuario(user_id: int):
    """Activa o desactiva un usuario."""
    if user_id == current_user.id:
        return jsonify({'success': False, 'message': 'No puedes desactivar tu propia cuenta.'}), 400

    usuario = db.session.get(Usuario, user_id)
    if not usuario:
        return jsonify({'success': False, 'message': 'Usuario no encontrado.'}), 404

    usuario.activo = not usuario.activo
    db.session.commit()

    estado = 'activado' if usuario.activo else 'desactivado'
    return jsonify({
        'success': True,
        'message': f'Usuario "{usuario.nombre}" {estado}.',
        'activo':  usuario.activo,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Cambiar rol
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route('/usuarios/<int:user_id>/rol', methods=['POST'])
@login_required
@requiere_permiso('usuarios.gestionar')
def cambiar_rol(user_id: int):
    """Asigna un único rol a un usuario (reemplaza los anteriores)."""
    payload = request.get_json(force=True) or {}
    rol_id  = payload.get('rol_id')

    usuario = db.session.get(Usuario, user_id)
    if not usuario:
        return jsonify({'success': False, 'message': 'Usuario no encontrado.'}), 404

    usuario.roles = []
    if rol_id:
        rol = db.session.get(Rol, int(rol_id))
        if rol:
            usuario.roles.append(rol)

    db.session.commit()

    rol_nombre = usuario.roles[0].nombre if usuario.roles else '(sin rol)'
    return jsonify({
        'success': True,
        'message': f'Rol actualizado: {rol_nombre}.',
        'rol':     rol_nombre,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Resetear contraseña
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route('/usuarios/<int:user_id>/reset-password', methods=['POST'])
@login_required
@requiere_permiso('usuarios.gestionar')
def reset_password(user_id: int):
    """Establece una nueva contraseña para el usuario."""
    payload      = request.get_json(force=True) or {}
    new_password = payload.get('password', '').strip()

    if len(new_password) < 8:
        return jsonify({'success': False, 'message': 'Mínimo 8 caracteres.'}), 400

    usuario = db.session.get(Usuario, user_id)
    if not usuario:
        return jsonify({'success': False, 'message': 'Usuario no encontrado.'}), 404

    usuario.set_password(new_password)
    db.session.commit()

    return jsonify({'success': True, 'message': f'Contraseña de "{usuario.nombre}" actualizada.'})


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route('/scheduler/estado')
@login_required
@requiere_permiso('usuarios.gestionar')
def scheduler_estado():
    """Devuelve el estado del scheduler como JSON."""
    from app.services.scheduler_service import get_status
    return jsonify(get_status())


@admin_bp.route('/scheduler/ejecutar-ahora', methods=['POST'])
@login_required
@requiere_permiso('usuarios.gestionar')
def scheduler_ejecutar_ahora():
    """Dispara el envío de pendientes inmediatamente."""
    from app.services.scheduler_service import ejecutar_ahora
    ejecutar_ahora(current_app._get_current_object())
    return jsonify({'success': True, 'message': 'Tarea iniciada en segundo plano.'})


# ─────────────────────────────────────────────────────────────────────────────
# Tipo de Cambio — CRUD
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route('/tipo-cambio')
@login_required
@requiere_permiso('usuarios.gestionar')
def tipo_cambio():
    """Panel de gestión del tipo de cambio diario."""
    from app.models.tipo_cambio import TipoCambio
    registros = TipoCambio.query.order_by(TipoCambio.fecha.desc()).all()
    return render_template('admin/tipo_cambio.html', registros=registros)


@admin_bp.route('/tipo-cambio/guardar', methods=['POST'])
@login_required
@requiere_permiso('usuarios.gestionar')
def tipo_cambio_guardar():
    """Guarda o actualiza el TC para una fecha individual."""
    from app.services.tipo_cambio_service import guardar_tipo_cambio
    from flask import flash, redirect, url_for
    from datetime import date

    fecha_str = request.form.get('fecha', '').strip()
    valor_str = request.form.get('valor', '').strip()

    if not fecha_str or not valor_str:
        flash('Fecha y valor son obligatorios.', 'danger')
        return redirect(url_for('admin.tipo_cambio'))

    try:
        fecha = date.fromisoformat(fecha_str)
        valor = float(valor_str.replace(',', '.'))
        if valor <= 0:
            raise ValueError
    except ValueError:
        flash('Fecha o valor inválidos.', 'danger')
        return redirect(url_for('admin.tipo_cambio'))

    guardar_tipo_cambio(fecha, valor)
    flash(f'Tipo de cambio {fecha_str} = {valor:.4f} guardado.', 'success')
    return redirect(url_for('admin.tipo_cambio'))


@admin_bp.route('/tipo-cambio/guardar-rango', methods=['POST'])
@login_required
@requiere_permiso('usuarios.gestionar')
def tipo_cambio_guardar_rango():
    """Carga masiva: aplica el mismo TC a todos los días del rango."""
    from app.services.tipo_cambio_service import guardar_rango
    from flask import flash, redirect, url_for
    from datetime import date

    fecha_ini_str = request.form.get('fecha_ini', '').strip()
    fecha_fin_str = request.form.get('fecha_fin', '').strip()
    valor_str     = request.form.get('valor', '').strip()

    try:
        fecha_ini = date.fromisoformat(fecha_ini_str)
        fecha_fin = date.fromisoformat(fecha_fin_str)
        valor     = float(valor_str.replace(',', '.'))
        if valor <= 0 or fecha_fin < fecha_ini:
            raise ValueError
    except ValueError:
        flash('Datos inválidos para el rango.', 'danger')
        return redirect(url_for('admin.tipo_cambio'))

    creados, actualizados = guardar_rango(fecha_ini, fecha_fin, valor)
    flash(f'Rango guardado: {creados} nuevos, {actualizados} actualizados.', 'success')
    return redirect(url_for('admin.tipo_cambio'))


@admin_bp.route('/tipo-cambio/eliminar/<int:tc_id>', methods=['POST'])
@login_required
@requiere_permiso('usuarios.gestionar')
def tipo_cambio_eliminar(tc_id: int):
    """Elimina un registro de tipo de cambio."""
    from app.services.tipo_cambio_service import eliminar_tipo_cambio
    from flask import flash, redirect, url_for
    eliminar_tipo_cambio(tc_id)
    flash('Registro eliminado.', 'success')
    return redirect(url_for('admin.tipo_cambio'))


# ─────────────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────────────

def _usuario_dict(u: Usuario) -> dict:
    return {
        'id':             u.id,
        'nombre':         u.nombre,
        'email':          u.email,
        'activo':         u.activo,
        'es_admin':       u.es_admin,
        'roles':          [r.nombre for r in u.roles],
        'fecha_creacion': u.fecha_creacion.strftime('%d/%m/%Y') if u.fecha_creacion else '',
        'ultimo_login':   u.ultimo_login.strftime('%d/%m/%Y %H:%M') if u.ultimo_login else '—',
    }

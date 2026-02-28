"""Seed de roles y permisos iniciales del sistema.

Uso: flask shell -c "exec(open('scripts/seed_rbac.py').read())"
  o: python scripts/seed_rbac.py (con FLASK_APP configurado)
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.usuario import Rol, Permiso

PERMISOS = [
    ('ventas.crear',       'Crear comprobantes de venta'),
    ('ventas.ver',         'Ver listado y detalle de comprobantes'),
    ('ventas.eliminar',    'Eliminar comprobantes en estado BORRADOR'),
    ('nc.crear',           'Emitir Notas de Crédito'),
    ('nd.crear',           'Emitir Notas de Débito'),
    ('reportes.ver',       'Ver reportes de ganancias'),
    ('reportes.exportar',  'Exportar reportes a Excel'),
    ('usuarios.gestionar', 'Gestionar usuarios y roles'),
    ('bulk.upload',        'Cargar masiva de comprobantes desde Excel'),
]

ROLES = {
    'Administrador': list(dict(PERMISOS).keys()),
    'Vendedor':      ['ventas.crear', 'ventas.ver', 'nc.crear', 'reportes.ver'],
    'Almacen':       ['ventas.ver', 'bulk.upload'],
    'Consulta':      ['ventas.ver', 'reportes.ver'],
}


def seed():
    app = create_app()
    with app.app_context():
        # Crear permisos
        permisos_map = {}
        for codigo, nombre in PERMISOS:
            p = Permiso.query.filter_by(codigo=codigo).first()
            if not p:
                p = Permiso(codigo=codigo, nombre=nombre)
                db.session.add(p)
                print(f'  [+] Permiso: {codigo}')
            permisos_map[codigo] = p

        # Crear roles y asignar permisos
        for nombre_rol, codigos in ROLES.items():
            rol = Rol.query.filter_by(nombre=nombre_rol).first()
            if not rol:
                rol = Rol(nombre=nombre_rol, descripcion=f'Rol {nombre_rol}')
                db.session.add(rol)
                print(f'  [+] Rol: {nombre_rol}')
            rol.permisos = [permisos_map[c] for c in codigos if c in permisos_map]

        db.session.commit()
        print('\nSeed RBAC completado.')


if __name__ == '__main__':
    seed()

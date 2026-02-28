"""Crea el usuario administrador inicial.

Uso: python scripts/create_admin.py
Requiere: .env configurado con DB_* y SECRET_KEY
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.usuario import Usuario, Rol


def create_admin():
    app = create_app()
    with app.app_context():
        email = input('Email del admin: ').strip()
        nombre = input('Nombre completo: ').strip()
        password = input('Contraseña: ').strip()

        if not email or not password:
            print('Email y contraseña son obligatorios.')
            sys.exit(1)

        if Usuario.query.filter_by(email=email).first():
            print(f'Ya existe un usuario con email {email}.')
            sys.exit(1)

        admin = Usuario(
            nombre=nombre,
            email=email,
            username=email.split('@')[0],
            es_admin=True,
            activo=True,
        )
        admin.set_password(password)

        # Asignar rol Administrador si existe
        rol_admin = Rol.query.filter_by(nombre='Administrador').first()
        if rol_admin:
            admin.roles.append(rol_admin)

        db.session.add(admin)
        db.session.commit()

        print(f'\nAdministrador creado exitosamente: {email}')


if __name__ == '__main__':
    create_admin()

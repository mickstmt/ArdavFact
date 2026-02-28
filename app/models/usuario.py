"""Modelos de usuario, rol y permiso (RBAC)."""
from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db, login_manager

# Tablas de asociación many-to-many
usuario_roles = db.Table(
    'usuario_roles',
    db.Column('usuario_id', db.Integer, db.ForeignKey('usuarios.id'), primary_key=True),
    db.Column('rol_id', db.Integer, db.ForeignKey('roles.id'), primary_key=True),
)

rol_permisos = db.Table(
    'rol_permisos',
    db.Column('rol_id', db.Integer, db.ForeignKey('roles.id'), primary_key=True),
    db.Column('permiso_id', db.Integer, db.ForeignKey('permisos.id'), primary_key=True),
)


class Usuario(db.Model, UserMixin):
    __tablename__ = 'usuarios'

    id             = db.Column(db.Integer, primary_key=True)
    nombre         = db.Column(db.String(100), nullable=False)
    username       = db.Column(db.String(50), unique=True, nullable=True)
    email          = db.Column(db.String(120), unique=True, nullable=False)
    password_hash  = db.Column(db.String(255), nullable=False)
    es_admin       = db.Column(db.Boolean, default=False)
    activo         = db.Column(db.Boolean, default=True)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    ultimo_login   = db.Column(db.DateTime, nullable=True)
    ip_registro    = db.Column(db.String(45), nullable=True)  # IPv6 compatible

    # Relaciones
    roles = db.relationship('Rol', secondary=usuario_roles, backref='usuarios', lazy='select')
    comprobantes = db.relationship(
        'Comprobante',
        backref='vendedor',
        foreign_keys='Comprobante.vendedor_id',
        lazy='dynamic',
    )

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def tiene_permiso(self, codigo: str) -> bool:
        """Verifica si el usuario tiene un permiso por código."""
        if self.es_admin:
            return True
        for rol in self.roles:
            for permiso in rol.permisos:
                if permiso.codigo == codigo:
                    return True
        return False

    def tiene_rol(self, nombre_rol: str) -> bool:
        return any(r.nombre == nombre_rol for r in self.roles)

    def __repr__(self):
        return f'<Usuario {self.email}>'


class Rol(db.Model):
    __tablename__ = 'roles'

    id          = db.Column(db.Integer, primary_key=True)
    nombre      = db.Column(db.String(50), unique=True, nullable=False)
    descripcion = db.Column(db.String(200))

    permisos = db.relationship('Permiso', secondary=rol_permisos, backref='roles', lazy='select')

    def __repr__(self):
        return f'<Rol {self.nombre}>'


class Permiso(db.Model):
    __tablename__ = 'permisos'

    id     = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    codigo = db.Column(db.String(50), unique=True, nullable=False)
    # Códigos definidos:
    # ventas.crear, ventas.ver, ventas.eliminar
    # nc.crear, nd.crear
    # reportes.ver, reportes.exportar
    # usuarios.gestionar
    # bulk.upload

    def __repr__(self):
        return f'<Permiso {self.codigo}>'


@login_manager.user_loader
def load_user(user_id: str):
    return db.session.get(Usuario, int(user_id))

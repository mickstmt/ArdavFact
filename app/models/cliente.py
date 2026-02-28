"""Modelo de cliente (persona natural o jurídica)."""
from datetime import datetime
from app.extensions import db


class Cliente(db.Model):
    __tablename__ = 'clientes'

    id               = db.Column(db.Integer, primary_key=True)
    tipo_documento   = db.Column(db.String(10), nullable=False)   # DNI, RUC, CE, PASAPORTE
    numero_documento = db.Column(db.String(15), unique=True, nullable=False)

    # Persona natural
    nombres          = db.Column(db.String(200), nullable=True)
    apellido_paterno = db.Column(db.String(100), nullable=True)
    apellido_materno = db.Column(db.String(100), nullable=True)

    # Persona jurídica (RUC 20)
    razon_social     = db.Column(db.String(200), nullable=True)
    nombre_comercial = db.Column(db.String(200), nullable=True)

    # Compartidos
    direccion        = db.Column(db.String(300), nullable=True)
    email            = db.Column(db.String(120), nullable=True)
    telefono         = db.Column(db.String(20), nullable=True)
    fecha_creacion   = db.Column(db.DateTime, default=datetime.utcnow)

    comprobantes = db.relationship('Comprobante', backref='cliente', lazy='dynamic')

    @property
    def nombre_completo(self) -> str:
        if self.tipo_documento == 'RUC':
            return self.razon_social or ''
        partes = [self.nombres or '', self.apellido_paterno or '', self.apellido_materno or '']
        return ' '.join(p for p in partes if p).strip()

    @property
    def codigo_tipo_documento_sunat(self) -> str:
        """Catálogo 06 SUNAT."""
        return {'DNI': '1', 'CE': '4', 'RUC': '6', 'PASAPORTE': '7'}.get(
            self.tipo_documento, '0'
        )

    @property
    def es_persona_juridica(self) -> bool:
        return self.tipo_documento == 'RUC'

    def __repr__(self):
        return f'<Cliente {self.tipo_documento}:{self.numero_documento}>'

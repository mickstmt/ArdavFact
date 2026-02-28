"""Modelo de plantilla de comprobante (diseño PDF personalizable)."""
from datetime import datetime
from app.extensions import db


class PlantillaComprobante(db.Model):
    __tablename__ = 'plantillas_comprobante'

    id                 = db.Column(db.Integer, primary_key=True)
    nombre             = db.Column(db.String(100))
    tipo               = db.Column(db.String(20))   # 'A4', 'TICKET_80MM'
    es_activo          = db.Column(db.Boolean, default=False)
    html_content       = db.Column(db.Text)
    css_content        = db.Column(db.Text)
    config_json        = db.Column(db.JSON, default=dict)
    fecha_creacion     = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_modificacion = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    def __repr__(self):
        return f'<PlantillaComprobante {self.nombre} [{self.tipo}]>'

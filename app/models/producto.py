"""Modelos de productos sincronizados desde WooCommerce."""
from datetime import datetime
from app.extensions import db

# Tabla de asociación producto <-> categoría
producto_categorias = db.Table(
    'producto_categorias',
    db.Column('producto_id', db.Integer, db.ForeignKey('productos.id'), primary_key=True),
    db.Column('categoria_id', db.Integer, db.ForeignKey('categorias.id'), primary_key=True),
)


class Categoria(db.Model):
    __tablename__ = 'categorias'

    id       = db.Column(db.Integer, primary_key=True)  # WooCommerce ID
    nombre   = db.Column(db.String(100))
    slug     = db.Column(db.String(100))
    padre_id = db.Column(db.Integer, db.ForeignKey('categorias.id'), nullable=True)
    count    = db.Column(db.Integer, default=0)

    hijos = db.relationship(
        'Categoria',
        backref=db.backref('padre', remote_side=[id]),
        lazy='select',
    )

    def __repr__(self):
        return f'<Categoria {self.nombre}>'


class Producto(db.Model):
    __tablename__ = 'productos'

    id                   = db.Column(db.Integer, primary_key=True)  # WooCommerce ID
    nombre               = db.Column(db.String(255))
    sku                  = db.Column(db.String(100), index=True)
    precio               = db.Column(db.Numeric(10, 2), default=0)        # Precio CON IGV
    precio_sin_igv       = db.Column(db.Numeric(10, 2), default=0)        # precio / 1.18
    stock_status         = db.Column(db.String(20), default='instock')
    imagen_url           = db.Column(db.Text, nullable=True)
    tipo                 = db.Column(db.String(20), default='simple')     # simple, variable
    fecha_sincronizacion = db.Column(db.DateTime, default=datetime.utcnow)

    variaciones = db.relationship(
        'Variacion', backref='producto', cascade='all, delete-orphan', lazy='select'
    )
    categorias = db.relationship(
        'Categoria', secondary=producto_categorias, backref='productos', lazy='select'
    )

    def __repr__(self):
        return f'<Producto {self.sku} - {self.nombre}>'


class Variacion(db.Model):
    __tablename__ = 'variaciones'

    id             = db.Column(db.Integer, primary_key=True)  # WooCommerce ID
    producto_id    = db.Column(db.Integer, db.ForeignKey('productos.id'))
    sku            = db.Column(db.String(100), index=True)
    precio         = db.Column(db.Numeric(10, 2), default=0)       # CON IGV
    precio_sin_igv = db.Column(db.Numeric(10, 2), default=0)       # precio / 1.18
    stock_status   = db.Column(db.String(20), default='instock')
    imagen_url     = db.Column(db.Text, nullable=True)
    atributos      = db.Column(db.JSON, nullable=False, default=dict)  # {"Color": "Negro", "Talla": "XL"}

    def __repr__(self):
        return f'<Variacion {self.sku}>'


class CostoProducto(db.Model):
    __tablename__ = 'costos_productos'

    id        = db.Column(db.Integer, primary_key=True)
    sku       = db.Column(db.String(100), index=True)
    desc      = db.Column(db.String(255))
    colorcode = db.Column(db.String(100))
    sizecode  = db.Column(db.String(100))
    costo     = db.Column(db.Numeric(10, 2), default=0)

    def __repr__(self):
        return f'<CostoProducto {self.sku}>'

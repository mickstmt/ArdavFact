"""Modelos de Comprobante y ComprobanteItem."""
from datetime import datetime
from app.extensions import db


class Comprobante(db.Model):
    __tablename__ = 'comprobantes'

    id = db.Column(db.Integer, primary_key=True)

    # === Identificación del comprobante ===
    tipo_comprobante     = db.Column(db.String(20), nullable=False)
    # Valores: FACTURA, BOLETA, NOTA_CREDITO, NOTA_DEBITO

    tipo_documento_sunat = db.Column(db.String(2), nullable=False)
    # Valores: '01' (Factura), '03' (Boleta), '07' (NC), '08' (ND)

    serie            = db.Column(db.String(10), nullable=False)   # F001, B001, FC01, BC01, FD01, BD01
    correlativo      = db.Column(db.String(10), nullable=False)   # sin ceros a la izquierda
    numero_completo  = db.Column(db.String(20), nullable=False)   # F001-00000001

    # === Relaciones principales ===
    cliente_id   = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    vendedor_id  = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    numero_orden = db.Column(db.String(20), nullable=True)  # WooCommerce order #

    # === Montos brutos ===
    subtotal    = db.Column(db.Numeric(12, 2), nullable=False, default=0)  # Suma ítems sin envío
    descuento   = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    costo_envio = db.Column(db.Numeric(12, 2), nullable=False, default=0)  # SIEMPRE campo, nunca ítem

    # === Desglose tributario ===
    total_operaciones_gravadas   = db.Column(db.Numeric(12, 2), default=0)  # Base imponible sin IGV
    total_operaciones_exoneradas = db.Column(db.Numeric(12, 2), default=0)
    total_operaciones_inafectas  = db.Column(db.Numeric(12, 2), default=0)
    total_operaciones_gratuitas  = db.Column(db.Numeric(12, 2), default=0)
    total_igv                    = db.Column(db.Numeric(12, 2), default=0)  # Monto IGV 18%
    total                        = db.Column(db.Numeric(12, 2), nullable=False, default=0)

    # === Estado y fechas ===
    estado = db.Column(db.String(20), default='BORRADOR', nullable=False)
    # Valores: BORRADOR, PENDIENTE, ENVIADO, ACEPTADO, RECHAZADO

    fecha_emision     = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    fecha_pedido      = db.Column(db.DateTime, nullable=True)   # Fecha original WooCommerce
    fecha_envio_sunat = db.Column(db.DateTime, nullable=True)
    fecha_vencimiento = db.Column(db.DateTime, nullable=True)   # Solo para Facturas

    # === Archivos y respuesta SUNAT ===
    xml_path      = db.Column(db.String(500), nullable=True)
    pdf_path      = db.Column(db.String(500), nullable=True)
    cdr_path      = db.Column(db.String(500), nullable=True)
    hash_cpe      = db.Column(db.String(100), nullable=True)
    mensaje_sunat = db.Column(db.Text, nullable=True)
    codigo_sunat  = db.Column(db.String(10), nullable=True)
    external_id   = db.Column(db.String(100), nullable=True)    # MiPSE UUID

    # === Referencias para NC y ND ===
    comprobante_referencia_id = db.Column(
        db.Integer, db.ForeignKey('comprobantes.id'), nullable=True
    )
    motivo_codigo      = db.Column(db.String(5), nullable=True)   # Catálogo 09 (NC) / 10 (ND)
    motivo_descripcion = db.Column(db.String(255), nullable=True)

    # === Relaciones ===
    items = db.relationship(
        'ComprobanteItem',
        backref='comprobante',
        cascade='all, delete-orphan',
        lazy='select',
    )
    comprobante_ref = db.relationship(
        'Comprobante',
        remote_side=[id],
        backref='notas_asociadas',
        foreign_keys=[comprobante_referencia_id],
    )

    __table_args__ = (
        db.UniqueConstraint('serie', 'correlativo', name='uq_serie_correlativo'),
    )

    @property
    def numero_sunat(self) -> str:
        """Número formateado para SUNAT: F001-00000001."""
        return f"{self.serie}-{str(self.correlativo).zfill(8)}"

    @property
    def es_nota(self) -> bool:
        return self.tipo_comprobante in ('NOTA_CREDITO', 'NOTA_DEBITO')

    @property
    def esta_enviado(self) -> bool:
        return self.estado in ('ENVIADO', 'ACEPTADO')

    def __repr__(self):
        return f'<Comprobante {self.numero_completo} [{self.estado}]>'


class ComprobanteItem(db.Model):
    __tablename__ = 'comprobante_items'

    id             = db.Column(db.Integer, primary_key=True)
    comprobante_id = db.Column(db.Integer, db.ForeignKey('comprobantes.id'), nullable=False)

    producto_nombre = db.Column(db.String(300), nullable=False)
    producto_sku    = db.Column(db.String(100), nullable=True)
    cantidad        = db.Column(db.Numeric(12, 2), nullable=False)
    unidad_medida   = db.Column(db.String(5), default='NIU')  # NIU=unidad, ZZ=servicio
    descuento       = db.Column(db.Numeric(12, 2), nullable=False, default=0)

    # === Precios ===
    precio_unitario_con_igv = db.Column(db.Numeric(12, 2), nullable=False)  # Lo que paga el cliente
    precio_unitario_sin_igv = db.Column(db.Numeric(12, 2), nullable=False)  # Base para SUNAT
    igv_unitario            = db.Column(db.Numeric(12, 2), nullable=False, default=0)

    # === Subtotales del ítem ===
    subtotal_sin_igv = db.Column(db.Numeric(12, 2), nullable=False)  # cantidad * precio_sin_igv
    igv_total        = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    subtotal_con_igv = db.Column(db.Numeric(12, 2), nullable=False)  # cantidad * precio_con_igv

    # === Tipo de afectación IGV (Catálogo 07 SUNAT) ===
    tipo_afectacion_igv = db.Column(db.String(2), default='10')
    # '10' = Gravado - Operación Onerosa (default para régimen general)
    # '20' = Exonerado - Operación Onerosa
    # '30' = Inafecto - Operación Onerosa
    # '40' = Exportación

    # === Datos WooCommerce ===
    variacion_id   = db.Column(db.Integer, nullable=True)
    atributos_json = db.Column(db.JSON, nullable=True)  # {"Color": "Negro", "Talla": "XL"}

    def __repr__(self):
        return f'<ComprobanteItem {self.producto_sku} x{self.cantidad}>'

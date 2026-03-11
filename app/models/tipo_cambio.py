from app.extensions import db


class TipoCambio(db.Model):
    __tablename__ = 'tipo_cambio'

    id    = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.Date, unique=True, nullable=False, index=True)
    valor = db.Column(db.Numeric(10, 4), nullable=False)

    def __repr__(self):
        return f'<TipoCambio {self.fecha} = {self.valor}>'

"""Servicio para gestión del Tipo de Cambio diario (USD → PEN)."""
from datetime import date as date_type, timedelta
from app.extensions import db
from app.models.tipo_cambio import TipoCambio


def get_tipo_cambio(fecha) -> float | None:
    """
    Retorna el tipo de cambio para una fecha dada.
    Si no existe registro exacto, usa el más reciente anterior.
    Retorna None si no hay ningún registro disponible.
    """
    if isinstance(fecha, date_type):
        f = fecha
    else:
        f = fecha.date() if hasattr(fecha, 'date') else fecha

    tc = (TipoCambio.query
          .filter(TipoCambio.fecha <= f)
          .order_by(TipoCambio.fecha.desc())
          .first())
    return float(tc.valor) if tc else None


def guardar_tipo_cambio(fecha: date_type, valor: float) -> TipoCambio:
    """Upsert: crea o actualiza el TC para una fecha específica."""
    registro = TipoCambio.query.filter_by(fecha=fecha).first()
    if registro:
        registro.valor = valor
    else:
        registro = TipoCambio(fecha=fecha, valor=valor)
        db.session.add(registro)
    db.session.commit()
    return registro


def guardar_rango(fecha_ini: date_type, fecha_fin: date_type, valor: float) -> tuple[int, int]:
    """
    Upsert del mismo TC para todos los días del rango [fecha_ini, fecha_fin].
    Retorna (creados, actualizados).
    """
    creados = actualizados = 0
    cursor = fecha_ini
    dias = (fecha_fin - fecha_ini).days + 1
    for _ in range(dias):
        registro = TipoCambio.query.filter_by(fecha=cursor).first()
        if registro:
            registro.valor = valor
            actualizados += 1
        else:
            db.session.add(TipoCambio(fecha=cursor, valor=valor))
            creados += 1
        cursor += timedelta(days=1)
    db.session.commit()
    return creados, actualizados


def eliminar_tipo_cambio(tc_id: int) -> None:
    """Elimina un registro de tipo de cambio por ID."""
    registro = TipoCambio.query.get_or_404(tc_id)
    db.session.delete(registro)
    db.session.commit()

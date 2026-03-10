"""Importa costos de productos desde un archivo CSV o Excel.

Formato esperado (columnas):
    SKU | Descripción | Color | Talla | Costo

Uso:
    python scripts/import_costos.py ruta/al/archivo.xlsx
    python scripts/import_costos.py ruta/al/archivo.csv
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from decimal import Decimal, InvalidOperation

from app import create_app
from app.extensions import db
from app.models.producto import CostoProducto


def importar_costos(ruta_archivo: str) -> None:
    ext = ruta_archivo.rsplit('.', 1)[-1].lower()
    if ext == 'csv':
        df = pd.read_csv(ruta_archivo, dtype=str)
    else:
        df = pd.read_excel(ruta_archivo, dtype=str)

    # Normalizar nombres de columnas
    df.columns = [c.strip().lower() for c in df.columns]

    creados = actualizados = errores = 0

    for _, row in df.iterrows():
        sku = str(row.get('sku', '') or '').strip()
        if not sku or sku in ('nan', 'None'):
            continue

        try:
            # Acepta columna 'costo' o 'fclastcost' (nombre del POS)
            costo_raw = (
                str(row.get('costo') or row.get('fclastcost', '0') or '0')
                .replace(',', '.').strip()
            )
            costo = Decimal(costo_raw) if costo_raw else Decimal('0')
        except InvalidOperation:
            costo = Decimal('0')
            errores += 1

        cp = CostoProducto.query.filter_by(sku=sku).first()
        if cp is None:
            cp = CostoProducto(sku=sku)
            db.session.add(cp)
            creados += 1
        else:
            actualizados += 1

        cp.desc      = str(row.get('descripcion', '') or row.get('desc1', '') or row.get('desc', '') or '').strip()
        cp.colorcode = str(row.get('color', '') or row.get('colorcode', '') or '').strip()
        cp.sizecode  = str(row.get('talla', '') or row.get('sizecode', '') or '').strip()
        cp.costo     = costo

    try:
        db.session.commit()
        print(f'Importación completada: {creados} nuevos, {actualizados} actualizados, {errores} filas con error de costo.')
    except Exception as exc:
        db.session.rollback()
        print(f'Error al guardar: {exc}')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Uso: python scripts/import_costos.py ruta/al/archivo.xlsx')
        sys.exit(1)

    ruta = sys.argv[1]
    if not os.path.exists(ruta):
        print(f'Archivo no encontrado: {ruta}')
        sys.exit(1)

    app = create_app()
    with app.app_context():
        importar_costos(ruta)

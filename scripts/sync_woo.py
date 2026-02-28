"""Sincronización manual de productos desde WooCommerce.

Uso:
    python scripts/sync_woo.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.services.woocommerce_service import sincronizar_todo

app = create_app()

with app.app_context():
    print('Iniciando sincronización WooCommerce…')
    stats = sincronizar_todo()

    cats  = stats['categorias']
    prods = stats['productos']

    print(f'\n  Categorías: {cats["creadas"]} nuevas, {cats["actualizadas"]} actualizadas, {cats["errores"]} errores')
    print(f'  Productos:  {prods["creados"]} nuevos, {prods["actualizados"]} actualizados, {prods["errores"]} errores')
    print('\nSincronización completada.')

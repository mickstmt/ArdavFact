"""Exporta todos los modelos para que Flask-Migrate los detecte."""
from .usuario import Usuario, Rol, Permiso, usuario_roles, rol_permisos
from .cliente import Cliente
from .producto import Producto, Variacion, Categoria, CostoProducto, producto_categorias
from .comprobante import Comprobante, ComprobanteItem
from .plantilla import PlantillaComprobante

__all__ = [
    'Usuario', 'Rol', 'Permiso', 'usuario_roles', 'rol_permisos',
    'Cliente',
    'Producto', 'Variacion', 'Categoria', 'CostoProducto', 'producto_categorias',
    'Comprobante', 'ComprobanteItem',
    'PlantillaComprobante',
]

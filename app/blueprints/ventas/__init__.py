from flask import Blueprint

ventas_bp = Blueprint('ventas', __name__, url_prefix='/ventas')

from . import routes  # noqa: F401, E402

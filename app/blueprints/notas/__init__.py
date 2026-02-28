from flask import Blueprint

notas_bp = Blueprint('notas', __name__, url_prefix='/notas')

from . import routes  # noqa: F401, E402

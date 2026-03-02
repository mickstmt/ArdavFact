from flask import Blueprint

comprobantes_bp = Blueprint('comprobantes', __name__, url_prefix='/comprobantes')

from . import routes  # noqa: F401, E402

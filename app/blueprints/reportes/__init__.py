from flask import Blueprint

reportes_bp = Blueprint('reportes', __name__, url_prefix='/reportes')

from . import routes  # noqa: F401, E402

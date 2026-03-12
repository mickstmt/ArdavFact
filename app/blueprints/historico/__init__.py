from flask import Blueprint

historico_bp = Blueprint('historico', __name__, url_prefix='/historico')

from . import routes  # noqa: F401, E402

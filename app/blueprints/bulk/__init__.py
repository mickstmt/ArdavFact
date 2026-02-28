from flask import Blueprint

bulk_bp = Blueprint('bulk', __name__, url_prefix='/bulk')

from . import routes  # noqa: F401, E402

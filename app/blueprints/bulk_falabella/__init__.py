from flask import Blueprint

bulk_falabella_bp = Blueprint('bulk_falabella', __name__, url_prefix='/bulk-falabella')

from . import routes  # noqa: F401, E402

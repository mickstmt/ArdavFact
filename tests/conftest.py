"""Fixtures de pytest para ArdavFact."""
import pytest
import flask
from app import create_app
from app.extensions import db as _db


@pytest.fixture(scope='session')
def app():
    """App configurada para tests (SQLite en memoria)."""
    _app = create_app('testing')
    _app.config.update({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'WTF_CSRF_ENABLED': False,
        'RATELIMIT_ENABLED': False,
    })
    with _app.app_context():
        _db.create_all()
        yield _app
        _db.drop_all()


@pytest.fixture(scope='function')
def db(app):
    """BD limpia por cada test."""
    with app.app_context():
        yield _db
        _db.session.rollback()


@pytest.fixture(scope='function')
def client(app):
    """Cliente HTTP de prueba.

    Limpia el caché g._login_user entre tests porque flask.g es app-scoped
    en Flask 2.2+ y el app_context del conftest persiste toda la sesión.
    """
    flask.g.pop('_login_user', None)
    return app.test_client()

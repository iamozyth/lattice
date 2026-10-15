import json
import logging
import os
from datetime import datetime, timedelta

from flask import jsonify, redirect, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager, current_user
from flask_openapi3 import OpenAPI
from flask_sqlalchemy import SQLAlchemy
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

VERSION = '1.0.0-beta.2'

# Header every state-changing API request must carry. Browsers only send
# custom headers cross-origin after a CORS preflight, which we never allow.
CSRF_HEADER = 'X-Requested-With'
CSRF_VALUE = 'lattice'


class JSONFormatter(logging.Formatter):
    def format(self, record):
        entry = {
            'timestamp': datetime.utcnow().isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
        }
        if record.exc_info:
            entry['exception'] = self.formatException(record.exc_info)
        return json.dumps(entry)


logging.basicConfig(level=getattr(logging, os.environ.get('LOG_LEVEL', 'INFO').upper(), logging.INFO))
if os.environ.get('LOG_FORMAT') == 'json':
    for handler in logging.root.handlers:
        handler.setFormatter(JSONFormatter())
logger = logging.getLogger(__name__)

db = SQLAlchemy()
login_manager = LoginManager()
# Only the endpoints that need it are limited (login, setup, scans, imports)
limiter = Limiter(key_func=get_remote_address, storage_uri='memory://')


def _env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'on')


def _database_url():
    url = os.environ.get('DATABASE_URL', 'postgresql://localhost:5432/lattice')
    # SQLAlchemy 2.1 defaults postgresql:// to psycopg 3; we ship psycopg2
    if url.startswith('postgresql://'):
        url = 'postgresql+psycopg2://' + url[len('postgresql://'):]
    return url


def create_app(config=None):
    basedir = os.path.abspath(os.path.dirname(__file__))
    app = OpenAPI(
        __name__,
        info={'title': 'Lattice API', 'version': VERSION,
              'description': 'IP address management API. Write requests need the header '
                             f'`{CSRF_HEADER}: {CSRF_VALUE}`.'},
        doc_prefix='/openapi',
    )
    app.static_folder = os.path.join(basedir, 'static')
    app.template_folder = os.path.join(basedir, 'templates')

    app.config.update(
        SQLALCHEMY_DATABASE_URI=_database_url(),
        SQLALCHEMY_ENGINE_OPTIONS={'pool_pre_ping': True},
        SECRET_KEY=os.environ.get('SECRET_KEY'),
        CONNECTOR_SECRET=os.environ.get('CONNECTOR_SECRET'),
        MAX_CONTENT_LENGTH=5 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=_env_bool('COOKIE_SECURE'),
        REMEMBER_COOKIE_HTTPONLY=True,
        REMEMBER_COOKIE_SAMESITE='Lax',
        REMEMBER_COOKIE_SECURE=_env_bool('COOKIE_SECURE'),
        REMEMBER_COOKIE_DURATION=timedelta(days=30),
        SCAN_INTERVAL_HOURS=float(os.environ.get('SCAN_INTERVAL_HOURS', 6)),
        STALE_DAYS=int(os.environ.get('STALE_DAYS', 30)),
        SCHEDULER_ENABLED=not _env_bool('LATTICE_NO_SCHEDULER'),
        RATELIMIT_ENABLED=True,
    )
    if config:
        app.config.update(config)

    if not app.config['SECRET_KEY']:
        raise RuntimeError('SECRET_KEY is not set. Generate one with: openssl rand -hex 32')

    if _env_bool('TRUST_PROXY'):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.session_protection = 'basic'
    limiter.init_app(app)

    @login_manager.unauthorized_handler
    def unauthorized():
        return jsonify({'error': 'Login required', 'code': 'AUTH_REQUIRED'}), 401

    @app.before_request
    def docs_need_login():
        if request.path.startswith('/openapi') and not current_user.is_authenticated:
            return redirect('/login')
        return None

    @app.before_request
    def require_csrf_header():
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return None
        if request.path.startswith('/api/') and request.headers.get(CSRF_HEADER) != CSRF_VALUE:
            return jsonify({'error': f'Missing {CSRF_HEADER} header'}), 403
        return None

    @app.after_request
    def security_headers(response):
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
        if request.path.startswith('/openapi'):
            # Swagger UI and Scalar ship inline scripts and load assets from their CDNs
            response.headers['Content-Security-Policy'] = (
                "default-src 'self' https://cdn.jsdelivr.net https://unpkg.com; "
                "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com https://fonts.googleapis.com; "
                "font-src 'self' data: https://fonts.gstatic.com https://cdn.jsdelivr.net; "
                "img-src 'self' data: https:; frame-ancestors 'none'")
        else:
            response.headers['Content-Security-Policy'] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "img-src 'self' data:; connect-src 'self'; base-uri 'none'; "
                "form-action 'self'; frame-ancestors 'none'")
        if request.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.errorhandler(HTTPException)
    def http_error(err):
        if request.path.startswith('/api/'):
            return jsonify({'error': err.description}), err.code
        return err

    from app.validation import ValidationError

    @app.errorhandler(ValidationError)
    def validation_error(err):
        db.session.rollback()
        return jsonify({'error': str(err)}), 400

    @app.errorhandler(Exception)
    def unhandled_error(err):
        db.session.rollback()
        logger.exception('Unhandled error on %s %s', request.method, request.path)
        return jsonify({'error': 'Internal server error'}), 500

    from app.auth import auth_bp
    from app.connectors.routes import connectors_bp
    from app.discovery import discovery_bp
    from app.routes import api_bp, main_bp

    app.register_api(auth_bp)
    app.register_api(api_bp)
    app.register_api(discovery_bp)
    app.register_api(connectors_bp)
    app.register_blueprint(main_bp)

    from flask_migrate import Migrate
    Migrate(app, db)

    @app.route('/health')
    def health():
        return {'status': 'healthy', 'version': VERSION}

    if app.config['SCHEDULER_ENABLED'] and not app.config.get('TESTING'):
        from app.scheduler import init_scheduler
        init_scheduler(app)

    return app

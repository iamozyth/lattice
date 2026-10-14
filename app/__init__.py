import os
import sys
import time
import logging
import json
from datetime import datetime
from flask import Flask, request, redirect, url_for, g
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_login import LoginManager, current_user
from flask_openapi3 import OpenAPI
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect

# Configure structured logging
class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_obj = {
            'timestamp': datetime.utcnow().isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
        }
        if hasattr(record, 'user_id'):
            log_obj['user_id'] = record.user_id
        if hasattr(record, 'ip'):
            log_obj['ip'] = record.ip
        if hasattr(record, 'action'):
            log_obj['action'] = record.action
        if record.exc_info:
            log_obj['exception'] = self.formatException(record.exc_info)
        return json.dumps(log_obj)

# Setup logging
log_format = os.environ.get('LOG_FORMAT', 'text')  # 'json' or 'text'
log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()

logging.basicConfig(level=getattr(logging, log_level, logging.INFO))
logger = logging.getLogger(__name__)

if log_format == 'json':
    for handler in logging.root.handlers:
        handler.setFormatter(JSONFormatter())

# Version constant
VERSION = '1.0.0-beta.1'

db = SQLAlchemy()
login_manager = LoginManager()
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per minute", "5000 per hour"],
    storage_uri="memory://",
)
csrf = CSRFProtect()

def validate_required_config():
    """Validate that required environment variables are set."""
    required_vars = []
    warnings = []

    # Check SECRET_KEY
    secret_key = os.environ.get('SECRET_KEY')
    if not secret_key:
        warnings.append("SECRET_KEY not set - using insecure default. Set SECRET_KEY in production!")
    elif secret_key == 'dev-secret-key-change-in-prod':
        warnings.append("SECRET_KEY is set to default value. Change it in production!")

    # Check DATABASE_URL
    if not os.environ.get('DATABASE_URL'):
        warnings.append("DATABASE_URL not set - using default. Configure for production!")

    # Check CONNECTOR_SECRET for production
    if os.environ.get('FLASK_ENV') == 'production':
        if not os.environ.get('CONNECTOR_SECRET'):
            warnings.append("CONNECTOR_SECRET not set - connector credentials will use default encryption key!")

    for warning in warnings:
        logger.warning(warning)

    return len(required_vars) == 0

def create_app():
    # Validate configuration
    validate_required_config()

    # Get the directory where this file is located
    basedir = os.path.abspath(os.path.dirname(__file__))

    # Use OpenAPI instead of Flask for automatic OpenAPI 3.0 spec generation
    app = OpenAPI(
        __name__,
        info={
            'title': 'Lattice API',
            'version': VERSION,
            'description': 'IP Address Management System API Documentation',
            'contact': {
                'name': 'Lattice',
            }
        }
    )

    # Enable OpenAPI spec generation
    app.config['OPENAPI_SPEC_PATH'] = '/openapi/openapi.json'

    # Configure Flask app
    app.static_folder = os.path.join(basedir, 'static')
    app.template_folder = os.path.join(basedir, 'templates')

    # Configuration with secure defaults
    database_url = os.environ.get('DATABASE_URL', 'postgresql://localhost:5432/lattice')
    # SQLAlchemy 2.1 defaults postgresql:// to psycopg 3; we ship psycopg2
    if database_url.startswith('postgresql://'):
        database_url = 'postgresql+psycopg2://' + database_url[len('postgresql://'):]
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-prod')

    # Session security settings
    app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FLASK_ENV') == 'production'
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['PERMANENT_SESSION_LIFETIME'] = 86400  # 24 hours

    # CSRF settings - exempt API endpoints that use token auth
    app.config['WTF_CSRF_CHECK_DEFAULT'] = False  # We'll check manually for forms
    app.config['WTF_CSRF_TIME_LIMIT'] = 3600  # 1 hour

    # Initialize extensions
    db.init_app(app)
    CORS(app, supports_credentials=True)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    limiter.init_app(app)
    csrf.init_app(app)

    # Exempt API routes from CSRF (they use session auth but are called via fetch)
    # In production, consider using API tokens instead
    @csrf.exempt
    @app.before_request
    def csrf_exempt_api():
        if request.path.startswith('/api/'):
            return None

    # For API requests, return JSON 401 instead of redirect loops
    @login_manager.unauthorized_handler
    def unauthorized():
        if request.path.startswith('/api/'):
            return {'error': 'Unauthorized', 'code': 'AUTH_REQUIRED'}, 401
        return redirect(url_for('auth.login'))

    # Security headers middleware
    @app.after_request
    def set_security_headers(response):
        # Prevent clickjacking
        response.headers['X-Frame-Options'] = 'DENY'
        # Prevent MIME type sniffing
        response.headers['X-Content-Type-Options'] = 'nosniff'
        # XSS protection (legacy but still useful)
        response.headers['X-XSS-Protection'] = '1; mode=block'
        # Referrer policy
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        # Permissions policy
        response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'

        # Content Security Policy (adjust as needed)
        if not request.path.startswith('/openapi'):
            response.headers['Content-Security-Policy'] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://cdnjs.cloudflare.com; "
                "style-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
                "font-src 'self' https://cdnjs.cloudflare.com https://fonts.gstatic.com; "
                "img-src 'self' data:; "
                "connect-src 'self'; "
                "frame-ancestors 'none';"
            )

        return response

    # Request logging middleware
    @app.before_request
    def log_request_start():
        g.request_start_time = time.time()

    @app.after_request
    def log_request_end(response):
        if hasattr(g, 'request_start_time'):
            duration = (time.time() - g.request_start_time) * 1000

            # Log requests (skip health checks and static files)
            if not request.path.startswith('/static') and request.path != '/health':
                log_data = {
                    'method': request.method,
                    'path': request.path,
                    'status': response.status_code,
                    'duration_ms': round(duration, 2),
                    'ip': request.remote_addr,
                }
                if current_user and hasattr(current_user, 'id') and current_user.is_authenticated:
                    log_data['user_id'] = current_user.id

                if response.status_code >= 400:
                    logger.warning(f"Request: {log_data}")
                elif duration > 1000:  # Log slow requests
                    logger.warning(f"Slow request: {log_data}")
                else:
                    logger.debug(f"Request: {log_data}")

        return response

    # Register blueprints
    from app.routes import api_bp, main_bp
    from app.auth import auth_bp

    # Use register_api for APIBlueprints (not register_blueprint)
    app.register_api(api_bp)
    app.register_api(auth_bp)

    # Use register_blueprint for standard Flask blueprints
    app.register_blueprint(main_bp)

    # Initialize Flask-Migrate for database schema management
    from flask_migrate import Migrate
    Migrate(app, db)

    # Initialize background scheduler
    with app.app_context():
        try:
            from app.scheduler import init_scheduler
            init_scheduler(app)
        except Exception as e:
            logger.warning(f"Failed to initialize scheduler: {e}. Continuing without background tasks.")

    # Health check
    @app.route('/health')
    def health():
        return {'status': 'healthy', 'version': VERSION}, 200

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)

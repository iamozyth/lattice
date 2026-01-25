import os
import time
import logging
from flask import Flask, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_login import LoginManager
from flask_openapi3 import OpenAPI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Version constant
VERSION = '1.0.0-beta.1'

db = SQLAlchemy()
login_manager = LoginManager()

def create_app():
    # Get the directory where this file is located
    basedir = os.path.abspath(os.path.dirname(__file__))
    
    # Use OpenAPI instead of Flask for automatic OpenAPI 3.0 spec generation
    app = OpenAPI(
        __name__,
        info={
            'title': 'NetDoc IPAM API',
            'version': '2.0.0',
            'description': 'IP Address Management System API Documentation',
            'contact': {
                'name': 'NetDoc IPAM Support',
            }
        }
    )
    
    # Enable OpenAPI spec generation
    app.config['OPENAPI_SPEC_PATH'] = '/openapi/openapi.json'
    
    # Configure Flask app
    app.static_folder = os.path.join(basedir, 'static')
    app.template_folder = os.path.join(basedir, 'templates')
    
    # Configuration
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
        'DATABASE_URL',
        'postgresql://ipam_user:ipam_secure_pass@localhost:5432/ipam_db'
    )
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-prod')
    
    # Initialize extensions
    db.init_app(app)
    CORS(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    
    # For API requests, return JSON 401 instead of redirect loops
    @login_manager.unauthorized_handler
    def unauthorized():
        if request.path.startswith('/api/'):
            return {'error': 'Unauthorized'}, 401
        return redirect(url_for('auth.login'))
    
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
        return {'status': 'healthy'}, 200
    
    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)

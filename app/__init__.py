import os
import time
import logging
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

db = SQLAlchemy()

def create_app():
    app = Flask(__name__)
    
    # Configuration
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
        'DATABASE_URL',
        'postgresql://ipam_user:ipam_secure_pass@localhost:5432/ipam_db'
    )
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # Initialize extensions
    db.init_app(app)
    CORS(app)
    
    # Register blueprints
    from app.routes import api_bp
    app.register_blueprint(api_bp)
    
    # Register static files
    from app.routes import static_bp
    app.register_blueprint(static_bp)
    
    # Create tables with retry logic
    with app.app_context():
        max_retries = 5
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                logger.info(f"Attempting to connect to database (attempt {attempt + 1}/{max_retries})...")
                db.create_all()
                logger.info("Database tables created successfully!")
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Database connection failed: {e}. Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    logger.error(f"Failed to connect to database after {max_retries} attempts: {e}")
                    raise
        
        # Initialize background scheduler
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

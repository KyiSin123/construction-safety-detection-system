"""Flask application factory: wires up shared extensions and registers each route blueprint."""

import os

from dotenv import load_dotenv
from flask import Flask, request
from werkzeug.security import generate_password_hash

load_dotenv()

import extensions
from extensions import MOBILE_WEB_ORIGINS, db, instance_detector, socketio
from routes.admin_api import admin_api_bp
from routes.detection import detection_bp, load_model
from routes.mobile_auth import mobile_auth_bp
from routes.pages import pages_bp
from routes.supervisor_api import supervisor_api_bp
from routes.video_analysis import video_analysis_bp
from routes.worker_api import worker_api_bp

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'development-only-change-me')
socketio.init_app(app, cors_allowed_origins="*", async_mode='threading')

app.register_blueprint(pages_bp)
app.register_blueprint(mobile_auth_bp)
app.register_blueprint(worker_api_bp)
app.register_blueprint(supervisor_api_bp)
app.register_blueprint(admin_api_bp)
app.register_blueprint(detection_bp)
app.register_blueprint(video_analysis_bp)


@app.after_request
def add_mobile_web_cors_headers(response):
    """Allow the Expo web development server to call the protected mobile API."""
    origin = request.headers.get('Origin', '').rstrip('/')
    if origin in MOBILE_WEB_ORIGINS:
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PATCH, DELETE, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Authorization, Content-Type'
        response.headers['Vary'] = 'Origin'
    return response


def _bootstrap():
    """Run once when this module loads -- both under `python app.py` and under a WSGI
    server like gunicorn, which imports `app` without ever hitting `__main__`."""
    try:
        db.init_db()
        initial_admin_username = os.getenv('SUPERVISOR_INITIAL_ADMIN_USERNAME')
        initial_admin_password = os.getenv('SUPERVISOR_INITIAL_ADMIN_PASSWORD')
        if initial_admin_username and initial_admin_password:
            db.seed_initial_admin(
                initial_admin_username,
                generate_password_hash(initial_admin_password),
                os.getenv('SUPERVISOR_INITIAL_ADMIN_NAME', initial_admin_username),
            )
        else:
            print('Supervisor bootstrap admin not created: configure SUPERVISOR_INITIAL_ADMIN_USERNAME and SUPERVISOR_INITIAL_ADMIN_PASSWORD')
        load_model()
        instance_detector.update_settings(extensions.current_settings)
    except Exception as e:
        print(f"Fatal error during startup: {e}")


_bootstrap()

if __name__ == '__main__':
    socketio.run(
        app,
        debug=os.getenv('FLASK_DEBUG', 'true').strip().lower() == 'true',
        host=os.getenv('FLASK_HOST', '0.0.0.0'),
        port=int(os.getenv('FLASK_PORT', '3333')),
        allow_unsafe_werkzeug=True,
    )

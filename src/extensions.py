"""Shared singletons, settings persistence, and small cross-blueprint helpers.

Every route blueprint imports from here instead of from `app.py`, which avoids
circular imports between the Flask app and the blueprints it registers.
"""

import json
import os
from functools import wraps

from flask import jsonify, request
from flask_socketio import SocketIO

from auth_service import AuthService
from database import Database
from detection_logic import ComplianceChecker, InstanceDetector, SnapshotManager
from identity_service import WorkerIdentityReader
from mobile_notification_service import ExpoPushNotifier

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

socketio = SocketIO()

db = Database()
instance_detector = InstanceDetector()
compliance_checker = ComplianceChecker()
snapshot_manager = SnapshotManager()
identity_reader = WorkerIdentityReader()
expo_push_notifier = ExpoPushNotifier()
auth_service = AuthService()

_model = None


def get_model():
    """Load the YOLO PPE-detection model once and share it across every blueprint that needs it.

    Imports ultralytics lazily so blueprints that never call this (the plain API routes) don't
    pay the torch/ultralytics import cost when only they are registered in a given deployment.
    """
    global _model
    if _model is None:
        from ultralytics import YOLO

        # Keep uploaded-file analysis and live camera detection on the same
        # fine-tuned PPE model. PPE_MODEL_PATH allows deployments to mount the
        # ignored weight file outside the repository.
        model_path = os.getenv(
            'PPE_MODEL_PATH',
            os.path.join(BASE_DIR, 'model', 'best.pt'),
        )
        if not os.path.isfile(model_path):
            raise FileNotFoundError(
                f'PPE model not found at {model_path}. Set PPE_MODEL_PATH to the '
                'trained best.pt file; the generic COCO model cannot detect PPE.'
            )
        _model = YOLO(model_path)
    return _model

MOBILE_WEB_ORIGINS = {
    origin.strip().rstrip('/')
    for origin in os.getenv(
        'MOBILE_WEB_ORIGINS',
        'http://localhost:8081,http://127.0.0.1:8081',
    ).split(',')
    if origin.strip()
}

HIDDEN_DISPLAY_CLASSES = set()

SETTINGS_FILE = os.path.join(BASE_DIR, 'settings.json')
DEFAULT_SETTINGS = {
    'required_ppe': {
        'helmet': True,
        'vest': True,
        'mask': False,
    },
    'non_compliance_delay': 3,
    'instance_reset_timeout': 5,
    'detection_mode': 'single',  # 'single' or 'multi'
}


def load_settings():
    """Load settings from file or return defaults."""
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"Error loading settings: {e}")
    return DEFAULT_SETTINGS.copy()


def save_settings_to_file(settings):
    """Save settings to file."""
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving settings: {e}")
        return False


# Mutated in place by routes/admin_api.py via `extensions.current_settings = ...`.
# Callers must read it as `extensions.current_settings`, not `from extensions import
# current_settings`, since the latter would freeze a stale reference at import time.
current_settings = load_settings()


def supervisor_profile(supervisor):
    return {
        'id': supervisor['id'],
        'username': supervisor['username'],
        'display_name': supervisor['display_name'],
        'role': supervisor['role'],
    }


def worker_profile(worker):
    return {
        'worker_number': worker['worker_number'], 'name': worker['name'], 'team': worker.get('team'),
        'phone': worker.get('phone'), 'email': worker.get('email'),
        'has_profile_photo': bool(worker.get('profile_photo_path')),
    }


def require_supervisor(admin_only=False):
    """Authenticate Bearer JWT requests and load a currently active supervisor."""
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not auth_service.configured:
                return jsonify({'error': 'Mobile API is not configured'}), 503
            authorization = request.headers.get('Authorization', '')
            token = authorization[7:] if authorization.startswith('Bearer ') else None
            claims = auth_service.verify_token(token)
            supervisor = db.get_supervisor(claims.get('sub')) if claims else None
            if not supervisor or not supervisor['is_active']:
                return jsonify({'error': 'Authentication required'}), 401
            if admin_only and supervisor['role'] != 'admin':
                return jsonify({'error': 'Administrator access required'}), 403
            return view(*args, supervisor=supervisor, **kwargs)
        return wrapped
    return decorator


def send_mobile_supervisor_notifications(instance_id, missing_ppe, identity):
    """Create recipient records once and push the assigned supervisors' registered devices."""
    recipients = db.create_supervisor_notifications(instance_id, identity)
    results = []
    for recipient in recipients:
        result = expo_push_notifier.send_violation(
            recipient['expo_push_token'],
            instance_id,
            identity.get('worker_name'),
            missing_ppe,
            identity.get('identity_status', 'unknown'),
            identity.get('worker_number'),
        )
        db.update_supervisor_notification_status(
            recipient['notification_id'], result['status'], result.get('error')
        )
        results.append({
            'supervisor_id': recipient['supervisor_id'],
            'supervisor_name': recipient['display_name'],
            'status': result['status'],
            'error': result.get('error'),
        })
    return results

"""Login endpoints for the supervisor and worker mobile apps."""

from flask import Blueprint, jsonify, request
from werkzeug.security import check_password_hash

from extensions import auth_service, db, supervisor_profile, worker_profile

mobile_auth_bp = Blueprint('mobile_auth', __name__)


@mobile_auth_bp.route('/api/mobile/auth/login', methods=['POST'])
def mobile_login():
    if not auth_service.configured:
        return jsonify({'error': 'SUPERVISOR_JWT_SECRET is not configured'}), 503
    payload = request.get_json(silent=True) or {}
    supervisor = db.get_supervisor_by_username(payload.get('username'))
    if not supervisor or not supervisor['is_active'] or not check_password_hash(
        supervisor['password_hash'], str(payload.get('password') or '')
    ):
        return jsonify({'error': 'Invalid username or password'}), 401
    return jsonify({
        'access_token': auth_service.issue_token(supervisor),
        'expires_in': auth_service.ttl_seconds,
        'supervisor': supervisor_profile(supervisor),
    })


@mobile_auth_bp.route('/api/worker/auth/login', methods=['POST'])
def worker_login():
    payload = request.get_json(silent=True) or {}
    worker = db.get_worker_for_login(payload.get('worker_number'))
    valid_password = worker and worker.get('password_hash') and check_password_hash(
        worker['password_hash'], str(payload.get('password') or '')
    )
    if not worker or not worker['is_active'] or not valid_password:
        return jsonify({'error': 'Invalid worker ID or password'}), 401
    return jsonify({
        'access_token': auth_service.issue_worker_token(worker),
        'worker': worker_profile(worker),
    })

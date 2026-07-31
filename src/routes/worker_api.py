"""Worker-facing mobile API: profile, violations, devices, attendance."""

import base64
import io
import os
import re
import uuid
from functools import wraps

from flask import Blueprint, jsonify, request, send_file, url_for
from PIL import Image
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import (
    BASE_DIR, auth_service, db, expo_push_notifier, resolve_media_path, worker_profile,
)

worker_api_bp = Blueprint('worker_api', __name__)


def require_worker(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        claims = auth_service.verify_token(request.headers.get('Authorization', '')[7:])
        worker = db.get_worker_for_login(claims.get('sub')) if claims and claims.get('account_type') == 'worker' else None
        if not worker or not worker['is_active']:
            return jsonify({'error': 'Worker authentication required'}), 401
        return view(*args, worker=worker, **kwargs)
    return wrapped


@worker_api_bp.route('/api/worker/me', methods=['GET', 'PATCH'])
@require_worker
def worker_me(worker):
    if request.method == 'GET':
        return jsonify(worker_profile(worker))
    payload = request.get_json(silent=True) or {}
    phone = str(payload.get('phone') or '').strip()
    email = str(payload.get('email') or '').strip().lower()
    if phone and (len(phone) > 32 or not re.fullmatch(r'[0-9+() .-]{5,32}', phone)):
        return jsonify({'error': 'Enter a valid phone number'}), 400
    if email and (len(email) > 255 or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email)):
        return jsonify({'error': 'Enter a valid email address'}), 400
    old_photo = worker.get('profile_photo_path')
    new_photo = None
    image_base64 = payload.get('image_base64')
    if image_base64:
        try:
            raw = base64.b64decode(str(image_base64).split(',')[-1], validate=True)
            if len(raw) > 5 * 1024 * 1024:
                raise ValueError('Profile photo must be 5 MB or smaller')
            image = Image.open(io.BytesIO(raw))
            image.verify()
            if image.format not in {'JPEG', 'PNG'}:
                raise ValueError('Profile photo must be JPEG or PNG')
            photo_dir = os.path.join(BASE_DIR, 'worker_profiles')
            os.makedirs(photo_dir, exist_ok=True)
            extension = '.jpg' if image.format == 'JPEG' else '.png'
            new_photo = os.path.join(photo_dir, f'{worker["worker_number"]}_{uuid.uuid4().hex}{extension}')
            with open(new_photo, 'wb') as output:
                output.write(raw)
        except Exception as error:
            return jsonify({'error': str(error) if isinstance(error, ValueError) else 'Invalid profile photo'}), 400
    ok, message, updated = db.update_worker_profile(worker['worker_number'], phone, email, new_photo)
    if not ok:
        if new_photo and os.path.isfile(new_photo):
            os.remove(new_photo)
        return jsonify({'error': message}), 400
    if new_photo and old_photo and old_photo != new_photo and os.path.isfile(old_photo):
        try:
            os.remove(old_photo)
        except OSError:
            pass
    return jsonify({'message': message, 'worker': worker_profile(updated)})


@worker_api_bp.route('/api/worker/profile-photo')
@require_worker
def worker_profile_photo(worker):
    path = worker.get('profile_photo_path')
    if not path or not os.path.isfile(path):
        return jsonify({'error': 'Profile photo not found'}), 404
    return send_file(path)


@worker_api_bp.route('/api/worker/password', methods=['PATCH'])
@require_worker
def worker_change_password(worker):
    payload = request.get_json(silent=True) or {}
    current = str(payload.get('current_password') or '')
    new = str(payload.get('new_password') or '')
    if not check_password_hash(worker.get('password_hash') or '', current):
        return jsonify({'error': 'Current password is incorrect'}), 400
    if len(new) < 8 or not re.search(r'[A-Za-z]', new) or not re.search(r'\d', new):
        return jsonify({'error': 'New password must be at least 8 characters and contain a letter and number'}), 400
    if not db.update_worker_password(worker['worker_number'], generate_password_hash(new)):
        return jsonify({'error': 'Unable to change password'}), 500
    return jsonify({'message': 'Password changed'})


@worker_api_bp.route('/api/worker/violations')
@require_worker
def worker_violations(worker):
    result = db.worker_violations(
        worker['worker_number'], request.args.get('page'), request.args.get('per_page'),
        request.args.get('status'), request.args.get('ppe'),
    )
    for item in result['items']:
        snapshot_id = item.pop('snapshot_id', None)
        item['snapshot_url'] = (
            url_for('worker_api.worker_snapshot', snapshot_id=snapshot_id)
            if snapshot_id else None
        )
    return jsonify(result)


@worker_api_bp.route('/api/worker/snapshots/<int:snapshot_id>')
@require_worker
def worker_snapshot(snapshot_id, worker):
    media = db.get_worker_snapshot_media(worker['worker_number'], snapshot_id)
    if not media:
        return jsonify({'error': 'Snapshot not found'}), 404
    path = resolve_media_path(media.get('path'))
    if path:
        return send_file(path, mimetype=media['mime_type'])
    if media.get('data'):
        return send_file(io.BytesIO(media['data']), mimetype=media['mime_type'])
    return jsonify({'error': 'Snapshot file is no longer available'}), 404

@worker_api_bp.route('/api/worker/violations/counts')
@require_worker
def worker_violation_counts(worker):
    return jsonify(db.worker_violation_counts(worker['worker_number']))


@worker_api_bp.route('/api/worker/devices', methods=['POST', 'DELETE'])
@require_worker
def worker_device(worker):
    payload = request.get_json(silent=True) or {}
    token = str(payload.get('expo_push_token') or '').strip()
    if request.method == 'DELETE':
        ok = db.deactivate_worker_device(worker['worker_number'], token or None)
        return jsonify({'status': 'success' if ok else 'error'}), 200 if ok else 500
    if not token.startswith('ExponentPushToken[') and not token.startswith('ExpoPushToken['):
        return jsonify({'error': 'A valid Expo push token is required'}), 400
    ok, message = db.register_worker_device(worker['worker_number'], token, payload.get('platform'))
    return jsonify({'status': 'success' if ok else 'error', 'message': message}), 200 if ok else 400


@worker_api_bp.route('/api/worker/attendance')
@require_worker
def worker_attendance(worker):
    return jsonify(db.worker_attendance(
        worker['worker_number'], request.args.get('page'), request.args.get('per_page'),
        request.args.get('month'), request.args.get('date'),
    ))


@worker_api_bp.route('/api/worker/attendance-requests', methods=['GET', 'POST'])
@require_worker
def worker_attendance_requests(worker):
    if request.method == 'GET':
        return jsonify(db.worker_attendance_requests(worker['worker_number']))
    payload = request.get_json(silent=True) or {}
    ok, message, request_id = db.create_attendance_request(
        worker['worker_number'], payload.get('action'), payload.get('requested_at'), payload.get('reason'),
    )
    if not ok:
        return jsonify({'error': message}), 400
    recipients = db.attendance_request_recipients(worker['worker_number'])
    sent = set()
    for recipient in recipients:
        token = recipient.get('expo_push_token')
        if token and token not in sent:
            expo_push_notifier.send_attendance_request(
                token, request_id, worker['name'], payload.get('action'), payload.get('requested_at'),
            )
            sent.add(token)
    return jsonify({
        'message': message, 'id': request_id,
        'notified_supervisors': len({r['supervisor_id'] for r in recipients}),
    }), 201


@worker_api_bp.route('/api/worker/violations/<instance_id>/proof', methods=['POST'])
@require_worker
def worker_submit_proof(instance_id, worker):
    payload = request.get_json(silent=True) or {}
    image = str(payload.get('image_base64') or '')
    comment = str(payload.get('comment') or '').strip()
    if not comment or not image:
        return jsonify({'error': 'Acknowledgement and a new proof photo are required'}), 400
    try:
        raw = base64.b64decode(image.split(',', 1)[-1], validate=True)
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError('Photo is too large')
        proof_dir = os.path.join(BASE_DIR, 'worker_proofs')
        os.makedirs(proof_dir, exist_ok=True)
        path = os.path.join(proof_dir, f'{instance_id}_{uuid.uuid4().hex}.jpg')
        open(path, 'wb').write(raw)
    except Exception:
        return jsonify({'error': 'Proof photo is invalid'}), 400
    ok, message = db.submit_worker_proof(worker['worker_number'], instance_id, comment, path)
    if not ok:
        try:
            os.remove(path)
        except OSError:
            pass
    return jsonify({'status': 'success' if ok else 'error', 'message': message}), 200 if ok else 400

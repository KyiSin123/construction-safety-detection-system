"""Supervisor-facing mobile API: violation feed, assignment, notifications, attendance review."""

import os

from flask import Blueprint, jsonify, request, send_file, url_for

from extensions import db, expo_push_notifier, require_supervisor, supervisor_profile

supervisor_api_bp = Blueprint('supervisor_api', __name__)


@supervisor_api_bp.route('/api/mobile/me')
@require_supervisor()
def mobile_me(supervisor):
    return jsonify(supervisor_profile(supervisor))


@supervisor_api_bp.route('/api/mobile/devices', methods=['POST', 'DELETE'])
@require_supervisor()
def mobile_device(supervisor):
    payload = request.get_json(silent=True) or {}
    token = str(payload.get('expo_push_token') or '').strip()
    if request.method == 'DELETE':
        db.deactivate_supervisor_device(supervisor['id'], token or None)
        return jsonify({'status': 'success'})
    if not token.startswith('ExponentPushToken[') and not token.startswith('ExpoPushToken['):
        return jsonify({'error': 'A valid Expo push token is required'}), 400
    ok, message = db.register_supervisor_device(supervisor['id'], token, payload.get('platform'))
    return jsonify({'status': 'success' if ok else 'error', 'message': message}), 200 if ok else 400


@supervisor_api_bp.route('/api/mobile/violations')
@require_supervisor()
def mobile_violations(supervisor):
    return jsonify(db.get_mobile_violations(supervisor['id'], request.args.get('status', 'pending')))


@supervisor_api_bp.route('/api/mobile/workers')
@require_supervisor()
def mobile_workers(supervisor):
    return jsonify(db.search_active_workers(request.args.get('search', '')))


@supervisor_api_bp.route('/api/mobile/violations/<instance_id>/assign-worker', methods=['POST'])
@require_supervisor()
def mobile_assign_worker(instance_id, supervisor):
    payload = request.get_json(silent=True) or {}
    ok, message, assignment = db.assign_worker_to_violation(
        supervisor, instance_id, payload.get('worker_number')
    )
    if not ok:
        return jsonify({'status': 'error', 'message': message}), 409 if 'already' in message else 400

    tokens = list(dict.fromkeys(assignment.pop('tokens')))
    missing_ppe = []
    detail = db.get_mobile_violation_detail(supervisor['id'], instance_id)
    if detail:
        missing_ppe = detail.get('missing_ppe') or []
    results = [
        expo_push_notifier.send_worker_violation(token, instance_id, missing_ppe)
        for token in tokens
    ]
    sent_count = sum(result['status'] == 'sent' for result in results)
    if not tokens:
        delivery_status, delivery_error = 'unavailable', 'Worker has no registered mobile device'
    elif sent_count:
        delivery_status, delivery_error = 'sent', None
    else:
        delivery_status = 'failed'
        delivery_error = '; '.join(
            result.get('error') for result in results if result.get('error')
        ) or 'Expo rejected the notification'
    db.update_worker_notification_status(
        assignment['notification_id'], delivery_status, delivery_error
    )
    assignment.pop('notification_id')
    return jsonify({
        'status': 'success', 'message': message, 'assignment': assignment,
        'delivery': {'status': delivery_status, 'sent_devices': sent_count,
                     'error': delivery_error},
    })


@supervisor_api_bp.route('/api/mobile/attendance-requests')
@require_supervisor()
def mobile_attendance_requests(supervisor):
    return jsonify(db.supervisor_attendance_requests(supervisor['id'], request.args.get('status', 'pending')))


@supervisor_api_bp.route('/api/mobile/attendance-requests/<int:request_id>/decision', methods=['PATCH'])
@require_supervisor()
def mobile_attendance_request_decision(request_id, supervisor):
    payload = request.get_json(silent=True) or {}
    ok, message = db.decide_attendance_request(supervisor, request_id, payload.get('decision'), payload.get('reason'))
    return jsonify({'status': 'success' if ok else 'error', 'message': message}), 200 if ok else 400


@supervisor_api_bp.route('/api/mobile/notifications/unread-count')
@require_supervisor()
def mobile_unread_notification_count(supervisor):
    return jsonify({'unread_count': db.get_mobile_unread_notification_count(supervisor['id'])})


@supervisor_api_bp.route('/api/mobile/notifications/read', methods=['POST'])
@require_supervisor()
def mobile_mark_notifications_read(supervisor):
    payload = request.get_json(silent=True) or {}
    ok, updated = db.mark_mobile_notification_read(supervisor['id'], payload.get('instance_id'))
    return jsonify({'status': 'success' if ok else 'error', 'updated': updated}), 200 if ok else 500


@supervisor_api_bp.route('/api/mobile/notifications/test', methods=['POST'])
@require_supervisor()
def mobile_test_notification(supervisor):
    """Send a direct Expo push test to the authenticated supervisor's registered devices."""
    device_tokens = db.get_active_supervisor_devices(supervisor['id'])
    if not device_tokens:
        return jsonify({'status': 'error', 'message': 'No registered mobile device. Sign in from the Android development build first.'}), 400
    results = [expo_push_notifier.send_test(device_token) for device_token in device_tokens]
    sent_count = sum(result['status'] == 'sent' for result in results)
    errors = [result.get('error') for result in results if result.get('error')]
    status_code = 200 if sent_count else 502
    return jsonify({
        'status': 'success' if sent_count else 'error',
        'message': f'Test notification accepted for {sent_count} device(s)' if sent_count else 'Expo rejected the test notification',
        'errors': errors,
    }), status_code


@supervisor_api_bp.route('/api/mobile/violations/<instance_id>')
@require_supervisor()
def mobile_violation_detail(instance_id, supervisor):
    data = db.get_mobile_violation_detail(supervisor['id'], instance_id)
    if not data:
        return jsonify({'error': 'Violation not found'}), 404
    for snapshot in data['snapshots']:
        snapshot['url'] = url_for('supervisor_api.mobile_snapshot', snapshot_id=snapshot['id'], _external=True)
    if data.get('review_status') == 'worker_submitted':
        data['worker_proof_url'] = url_for('supervisor_api.mobile_worker_proof', instance_id=instance_id, _external=True)
    return jsonify(data)


@supervisor_api_bp.route('/api/mobile/violations/<instance_id>/worker-proof')
@require_supervisor()
def mobile_worker_proof(instance_id, supervisor):
    path = db.get_worker_proof_path(supervisor['id'], instance_id)
    if not path or not os.path.isfile(path):
        return jsonify({'error': 'Worker proof not found'}), 404
    return send_file(path, mimetype='image/jpeg')


@supervisor_api_bp.route('/api/mobile/violations/<instance_id>/review', methods=['PATCH'])
@require_supervisor()
def mobile_update_review(instance_id, supervisor):
    payload = request.get_json(silent=True) or {}
    ok, message = db.update_mobile_review(
        supervisor, instance_id, payload.get('review_status'), payload.get('review_reason')
    )
    return jsonify({'status': 'success' if ok else 'error', 'message': message}), 200 if ok else 400


@supervisor_api_bp.route('/api/mobile/snapshots/<int:snapshot_id>')
@require_supervisor()
def mobile_snapshot(snapshot_id, supervisor):
    path = db.get_mobile_snapshot_path(supervisor['id'], snapshot_id)
    if not path or not os.path.isfile(path):
        return jsonify({'error': 'Snapshot not found'}), 404
    return send_file(path, mimetype='image/jpeg')

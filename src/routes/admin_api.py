"""Admin dashboard API: supervisors, settings, worker registry, attendance, violation instances."""

from flask import Blueprint, jsonify, request
from werkzeug.security import generate_password_hash

import extensions
from extensions import db, instance_detector, require_supervisor

admin_api_bp = Blueprint('admin_api', __name__)


@admin_api_bp.route('/api/admin/supervisors', methods=['GET', 'POST'])
@require_supervisor(admin_only=True)
def admin_supervisors(supervisor):
    if request.method == 'GET':
        return jsonify(db.get_supervisors())
    payload = request.get_json(silent=True) or {}
    password = str(payload.get('password') or '')
    password_hash = generate_password_hash(password) if password else None
    ok, message, supervisor_id = db.save_supervisor(payload, password_hash)
    if not ok:
        return jsonify({'status': 'error', 'message': message}), 400
    assignments_ok, assignments_message = db.set_supervisor_assignments(
        supervisor_id, payload.get('worker_numbers'), payload.get('teams')
    )
    return jsonify({
        'status': 'success' if assignments_ok else 'error',
        'message': assignments_message if not assignments_ok else message,
        'id': supervisor_id,
    }), 200 if assignments_ok else 400


@admin_api_bp.route('/api/admin/settings', methods=['GET'])
@require_supervisor(admin_only=True)
def get_settings(supervisor):
    """Get current settings."""
    return jsonify(extensions.current_settings)


@admin_api_bp.route('/api/admin/settings', methods=['POST'])
@require_supervisor(admin_only=True)
def update_settings(supervisor):
    """Update settings."""
    try:
        new_settings = request.json
        extensions.current_settings = new_settings
        instance_detector.update_settings(new_settings)
        if extensions.save_settings_to_file(new_settings):
            return jsonify({'status': 'success', 'message': 'Settings saved'})
        return jsonify({'status': 'error', 'message': 'Failed to save settings to file'}), 500
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@admin_api_bp.route('/api/admin/settings/reset', methods=['POST'])
@require_supervisor(admin_only=True)
def reset_settings(supervisor):
    """Reset settings to defaults."""
    try:
        extensions.current_settings = extensions.DEFAULT_SETTINGS.copy()
        instance_detector.update_settings(extensions.current_settings)
        if extensions.save_settings_to_file(extensions.current_settings):
            return jsonify({
                'status': 'success', 'message': 'Settings reset to defaults',
                'settings': extensions.current_settings,
            })
        return jsonify({'status': 'error', 'message': 'Failed to save settings to file'}), 500
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@admin_api_bp.route('/api/admin/workers', methods=['GET'])
@require_supervisor(admin_only=True)
def get_workers(supervisor):
    """List registered workers."""
    return jsonify(db.get_workers(include_inactive=True))


@admin_api_bp.route('/api/admin/workers', methods=['POST'])
@require_supervisor(admin_only=True)
def save_worker(supervisor):
    """Create or update a worker."""
    payload = request.json or {}
    password = str(payload.get('password') or '')
    ok, message = db.save_worker(payload, generate_password_hash(password) if password else None)
    status_code = 200 if ok else 400
    return jsonify({'status': 'success' if ok else 'error', 'message': message}), status_code


@admin_api_bp.route('/api/admin/workers/<worker_number>', methods=['DELETE'])
@require_supervisor(admin_only=True)
def delete_worker(worker_number, supervisor):
    """Delete a worker from the registry."""
    if db.delete_worker(worker_number):
        return jsonify({'status': 'success', 'message': 'Worker deleted'})
    return jsonify({'error': 'Failed to delete worker'}), 500


@admin_api_bp.route('/api/admin/attendance', methods=['GET', 'POST'])
@require_supervisor(admin_only=True)
def admin_attendance(supervisor):
    if request.method == 'GET':
        return jsonify(db.get_attendance(request.args.get('date')))
    payload = request.get_json(silent=True) or {}
    ok, message, worker = db.record_attendance(
        payload.get('worker_number'), payload.get('action'), supervisor.get('display_name'),
        payload.get('recorded_at'), payload.get('reason')
    )
    return jsonify({'status': 'success' if ok else 'error', 'message': message, 'worker': worker}), 200 if ok else 400


@admin_api_bp.route('/api/admin/instances')
@require_supervisor(admin_only=True)
def get_instances(supervisor):
    """Get all detection instances."""
    try:
        sort_by = request.args.get('sort', 'first_detected')
        sort_order = request.args.get('order', 'desc')
        status = request.args.get('status')
        instances = db.get_all_instances(sort_by, sort_order, status)
        return jsonify(instances)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_api_bp.route('/api/admin/detection-analysis')
@require_supervisor(admin_only=True)
def get_detection_analysis(supervisor):
    """Return dashboard-ready aggregates for recent persisted detections."""
    try:
        days = int(request.args.get('days', 7))
    except (TypeError, ValueError):
        days = 7
    if days not in {7, 30, 90}:
        days = 7

    analysis = db.get_detection_analysis(days)
    if analysis is None:
        return jsonify({'error': 'Unable to load detection analysis'}), 500
    return jsonify(analysis)


@admin_api_bp.route('/api/admin/instances/<instance_id>/review', methods=['PATCH'])
@require_supervisor(admin_only=True)
def update_instance_review(instance_id, supervisor):
    """Update review status and reason for a violation instance."""
    try:
        payload = request.get_json(silent=True) or {}
        ok, message = db.update_instance_review(
            instance_id=instance_id,
            review_status=payload.get('review_status'),
            review_reason=payload.get('review_reason'),
            reviewed_by=payload.get('reviewed_by')
        )
        status_code = 200 if ok else 400
        return jsonify({'status': 'success' if ok else 'error', 'message': message}), status_code
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@admin_api_bp.route('/api/admin/instances/<instance_id>/snapshots')
@require_supervisor(admin_only=True)
def get_instance_snapshots(instance_id, supervisor):
    """Get all snapshots for a specific instance."""
    try:
        data = db.get_instance_snapshots(instance_id)
        if data:
            return jsonify(data)
        return jsonify({'error': 'Instance not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_api_bp.route('/api/admin/instances/<instance_id>', methods=['DELETE'])
@require_supervisor(admin_only=True)
def delete_instance(instance_id, supervisor):
    """Delete an instance and its snapshot."""
    try:
        success = db.delete_instance(instance_id)
        if success:
            return jsonify({'status': 'success', 'message': 'Instance deleted'})
        return jsonify({'error': 'Failed to delete instance'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

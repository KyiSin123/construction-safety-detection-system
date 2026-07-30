"""HTML page routes for the detection operator and admin dashboards."""

from flask import Blueprint, redirect, render_template

pages_bp = Blueprint('pages', __name__)


@pages_bp.route('/')
def index():
    """Detection operator frontend. Live camera controls only work where a camera is
    attached (i.e. not on a typical cloud deployment) -- see /analyze for the
    upload-based alternative that works anywhere."""
    return render_template('index.html')


@pages_bp.route('/admin')
def admin_dashboard():
    """Separate administrator frontend for site management."""
    return render_template('admin.html')


@pages_bp.route('/analyze')
def analyze():
    """Stateless PPE-detection preview: upload an image or clip, no camera required."""
    return render_template('analyze.html')


@pages_bp.route('/admin/review')
def review():
    """Administrator violation-history page."""
    return render_template('review.html')


@pages_bp.route('/admin/settings')
def settings():
    """Administrator detection-settings page."""
    return render_template('settings.html')


@pages_bp.route('/admin/workers')
def workers():
    """Administrator worker registry page."""
    return render_template('workers.html')


@pages_bp.route('/admin/supervisors')
def supervisors():
    """Administrator supervisor-account page."""
    return render_template('supervisors.html')


@pages_bp.route('/admin/attendance')
def attendance():
    """Administrator worker attendance page."""
    return render_template('attendance.html')


@pages_bp.route('/review')
@pages_bp.route('/settings')
@pages_bp.route('/workers')
@pages_bp.route('/supervisors')
def legacy_admin_routes():
    """Keep prior bookmarks out of the detection frontend."""
    return redirect('/admin')

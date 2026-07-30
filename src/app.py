from flask import Flask, render_template, Response, jsonify, request, send_file, url_for, redirect
from flask_socketio import SocketIO, emit
from dotenv import load_dotenv
from werkzeug.security import check_password_hash, generate_password_hash
from functools import wraps
import cv2
from ultralytics import YOLO
from datetime import datetime, timedelta
import os
import threading
import time
from PIL import Image
from detection_logic import InstanceDetector, ComplianceChecker, SnapshotManager
from database import Database
from identity_service import WorkerIdentityReader, ViolationCropBuffer, select_worker_crop
from auth_service import AuthService
from mobile_notification_service import ExpoPushNotifier
import json
import base64
import uuid
import io
import re

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'development-only-change-me')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

MOBILE_WEB_ORIGINS = {
    origin.strip().rstrip('/')
    for origin in os.getenv(
        'MOBILE_WEB_ORIGINS',
        'http://localhost:8081,http://127.0.0.1:8081',
    ).split(',')
    if origin.strip()
}


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

model = None
camera = None
streaming = False
stream_lock = threading.Lock()
dev_mode = False
db = Database()
instance_detector = InstanceDetector()
compliance_checker = ComplianceChecker()
snapshot_manager = SnapshotManager()
identity_reader = WorkerIdentityReader()
expo_push_notifier = ExpoPushNotifier()
auth_service = AuthService()

HIDDEN_DISPLAY_CLASSES = set()
SETTINGS_FILE = os.path.join(BASE_DIR, 'settings.json')
DEFAULT_SETTINGS = {
    'required_ppe': {
        'helmet': True,
        'vest': True,
        'mask': False
    },
    'non_compliance_delay': 3,
    'instance_reset_timeout': 5,
    'detection_mode': 'single'  # 'single' or 'multi'
}

def load_settings():
    """Load settings from file or return defaults"""
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"Error loading settings: {e}")
    return DEFAULT_SETTINGS.copy()

def save_settings_to_file(settings):
    """Save settings to file"""
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving settings: {e}")
        return False

current_settings = load_settings()


def supervisor_profile(supervisor):
    return {
        'id': supervisor['id'],
        'username': supervisor['username'],
        'display_name': supervisor['display_name'],
        'role': supervisor['role'],
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

def require_worker(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        claims = auth_service.verify_token(request.headers.get('Authorization','')[7:])
        worker = db.get_worker_for_login(claims.get('sub')) if claims and claims.get('account_type') == 'worker' else None
        if not worker or not worker['is_active']: return jsonify({'error':'Worker authentication required'}),401
        return view(*args, worker=worker, **kwargs)
    return wrapped


def worker_profile(worker):
    return {
        'worker_number': worker['worker_number'], 'name': worker['name'], 'team': worker.get('team'),
        'phone': worker.get('phone'), 'email': worker.get('email'),
        'has_profile_photo': bool(worker.get('profile_photo_path')),
    }


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
            'status': result['status'],
            'error': result.get('error'),
        })
    return results

def hide_classes_for_display(result):
    """Return a result copy without classes that should not be drawn."""
    if result.boxes is None:
        return result

    keep_indices = [
        i for i, cls in enumerate(result.boxes.cls)
        if model.names[int(cls)] not in HIDDEN_DISPLAY_CLASSES
    ]
    return result[keep_indices]

def load_model():
    """Load YOLO model"""
    global model
    model_path = os.path.join(
        BASE_DIR, '..', 'Model-Training', 'Outputs', 'runs', 'detect',
        'yolov8s_ppe_css_80_epochs', 'weights', 'best.pt',
    )
    if os.path.exists(model_path):
        model = YOLO(model_path)
    else:
        model = YOLO('yolov8n.pt')

def generate_frames():
    """Generate video frames with instance detection"""
    global camera, streaming, model, current_settings
    
    last_alert_time = 0
    ALERT_COOLDOWN = current_settings['non_compliance_delay']
    last_snapshot_time = 0
    SNAPSHOT_INTERVAL = current_settings['instance_reset_timeout']
    crop_buffer = ViolationCropBuffer()
    
    while streaming:
        try:
            with stream_lock:
                if camera is None or not camera.isOpened():
                    break
                
                success, frame = camera.read()
            
            if not success or frame is None:
                time.sleep(0.1)
                continue
            
            results = model(frame)
            
            all_detections = []
            for result in results:
                boxes = result.boxes
                for box in boxes:
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                    conf = float(box.conf[0])
                    cls = int(box.cls[0])
                    class_name = model.names[cls]
                    
                    all_detections.append({
                        'class': class_name,
                        'confidence': conf,
                        'bbox': [int(x1), int(y1), int(x2), int(y2)]
                    })
            
            instance_result = instance_detector.process_detection(all_detections, dev_mode, current_settings)
            is_compliant = compliance_checker.check_compliance(instance_result, dev_mode)
            if not is_compliant and instance_result['has_person']:
                crop_buffer.add(select_worker_crop(frame, all_detections))
            else:
                crop_buffer.clear()
            
            annotated_frame = hide_classes_for_display(results[0]).plot()
            
            current_time = time.time()
            
            if instance_result['should_capture'] and (current_time - last_snapshot_time) >= SNAPSHOT_INTERVAL:
                worker_crop = crop_buffer.best()
                if worker_crop is None:
                    worker_crop = select_worker_crop(frame, all_detections)
                identity_result = identity_reader.identify_worker(worker_crop, db)
                identity_data = identity_result.to_dict()
                blocking_instance_id = db.find_blocking_violation(
                    instance_result['missing_ppe'],
                    identity_data
                )

                if blocking_instance_id:
                    instance_result['identity'] = identity_data
                    instance_result['storage_status'] = 'skipped_duplicate'
                    instance_result['existing_instance_id'] = blocking_instance_id
                    print(
                        "Skipped duplicate violation storage: "
                        f"{instance_result['instance_id']} blocked by {blocking_instance_id}"
                    )
                else:
                    snapshot_filename = instance_detector.get_next_snapshot_filename()
                    if snapshot_filename:
                        snapshot_path = snapshot_manager.save_snapshot(frame, snapshot_filename)

                        if not snapshot_path:
                            instance_result['storage_status'] = 'snapshot_failed'
                        else:
                            logged = db.log_instance_snapshot(
                                instance_id=instance_result['instance_id'],
                                missing_ppe=instance_result['missing_ppe'],
                                detected_ppe=instance_result['detected_ppe'],
                                snapshot_path=snapshot_path,
                                identity=identity_data
                            )

                            instance_result['identity'] = identity_data
                            if logged:
                                instance_result['mobile_notifications'] = send_mobile_supervisor_notifications(
                                    instance_result['instance_id'],
                                    instance_result['missing_ppe'],
                                    identity_data,
                                )
                                instance_result['storage_status'] = 'stored'
                                last_snapshot_time = current_time
                            else:
                                instance_result['storage_status'] = 'store_failed'
                    else:
                        instance_result['storage_status'] = 'snapshot_filename_unavailable'
            
            if not is_compliant and instance_result['has_person']:
                overlay = annotated_frame.copy()
                cv2.rectangle(overlay, (0, 0), (annotated_frame.shape[1], annotated_frame.shape[0]), 
                             (0, 0, 255), 20)
                annotated_frame = cv2.addWeighted(annotated_frame, 0.8, overlay, 0.2, 0)
                
                alert_text = "DEV MODE - TESTING" if dev_mode else "NON-COMPLIANT DETECTED"
                cv2.putText(annotated_frame, alert_text, 
                           (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3)
                
                if current_time - last_alert_time > ALERT_COOLDOWN:
                    worker_name = instance_result.get('identity', {}).get('worker_name')
                    description = (
                        f"PPE non-compliance detected: {worker_name}"
                        if worker_name else "PPE non-compliance detected"
                    )
                    socketio.emit('alert', {
                        'timestamp': datetime.now().isoformat(),
                        'type': 'NON_COMPLIANCE',
                        'description': description,
                        'dev_mode': dev_mode
                    })
                    last_alert_time = current_time
            
            socketio.emit('detection_update', {
                'timestamp': datetime.now().isoformat(),
                'is_compliant': is_compliant,
                'detection_details': instance_result,
                'dev_mode': dev_mode
            })
            
            ret, buffer = cv2.imencode('.jpg', annotated_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if not ret:
                continue
                
            frame_bytes = buffer.tobytes()
            
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        
        except GeneratorExit:
            break
        except Exception as e:
            print(f"Error in generate_frames: {e}")
            break

@app.route('/')
def index():
    """Detection operator frontend."""
    return render_template('index.html')

@app.route('/admin')
def admin_dashboard():
    """Separate administrator frontend for site management."""
    return render_template('admin.html')

@app.route('/admin/review')
def review():
    """Administrator violation-history page."""
    return render_template('review.html')

@app.route('/admin/settings')
def settings():
    """Administrator detection-settings page."""
    return render_template('settings.html')

@app.route('/admin/workers')
def workers():
    """Administrator worker registry page."""
    return render_template('workers.html')

@app.route('/admin/supervisors')
def supervisors():
    """Administrator supervisor-account page."""
    return render_template('supervisors.html')


@app.route('/admin/attendance')
def attendance():
    """Administrator worker attendance page."""
    return render_template('attendance.html')


@app.route('/review')
@app.route('/settings')
@app.route('/workers')
@app.route('/supervisors')
def legacy_admin_routes():
    """Keep prior bookmarks out of the detection frontend."""
    return redirect('/admin')


@app.route('/api/mobile/auth/login', methods=['POST'])
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

@app.route('/api/worker/auth/login', methods=['POST'])
def worker_login():
    payload=request.get_json(silent=True) or {}; worker=db.get_worker_for_login(payload.get('worker_number'))
    if not worker or not worker['is_active'] or not worker.get('password_hash') or not check_password_hash(worker['password_hash'],str(payload.get('password') or '')): return jsonify({'error':'Invalid worker ID or password'}),401
    return jsonify({'access_token':auth_service.issue_worker_token(worker),'worker':worker_profile(worker)})

@app.route('/api/worker/me', methods=['GET', 'PATCH'])
@require_worker
def worker_me(worker):
    if request.method == 'GET': return jsonify(worker_profile(worker))
    payload=request.get_json(silent=True) or {}
    phone=str(payload.get('phone') or '').strip(); email=str(payload.get('email') or '').strip().lower()
    if phone and (len(phone)>32 or not re.fullmatch(r'[0-9+() .-]{5,32}',phone)):
        return jsonify({'error':'Enter a valid phone number'}),400
    if email and (len(email)>255 or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',email)):
        return jsonify({'error':'Enter a valid email address'}),400
    old_photo=worker.get('profile_photo_path'); new_photo=None
    image_base64=payload.get('image_base64')
    if image_base64:
        try:
            raw=base64.b64decode(str(image_base64).split(',')[-1],validate=True)
            if len(raw)>5*1024*1024: raise ValueError('Profile photo must be 5 MB or smaller')
            image=Image.open(io.BytesIO(raw)); image.verify()
            if image.format not in {'JPEG','PNG'}: raise ValueError('Profile photo must be JPEG or PNG')
            photo_dir=os.path.join(BASE_DIR,'worker_profiles'); os.makedirs(photo_dir,exist_ok=True)
            extension='.jpg' if image.format=='JPEG' else '.png'
            new_photo=os.path.join(photo_dir,f'{worker["worker_number"]}_{uuid.uuid4().hex}{extension}')
            with open(new_photo,'wb') as output: output.write(raw)
        except Exception as error:
            return jsonify({'error':str(error) if isinstance(error,ValueError) else 'Invalid profile photo'}),400
    ok,message,updated=db.update_worker_profile(worker['worker_number'],phone,email,new_photo)
    if not ok:
        if new_photo and os.path.isfile(new_photo): os.remove(new_photo)
        return jsonify({'error':message}),400
    if new_photo and old_photo and old_photo!=new_photo and os.path.isfile(old_photo):
        try: os.remove(old_photo)
        except OSError: pass
    return jsonify({'message':message,'worker':worker_profile(updated)})

@app.route('/api/worker/profile-photo')
@require_worker
def worker_profile_photo(worker):
    path=worker.get('profile_photo_path')
    if not path or not os.path.isfile(path): return jsonify({'error':'Profile photo not found'}),404
    return send_file(path)

@app.route('/api/worker/password',methods=['PATCH'])
@require_worker
def worker_change_password(worker):
    payload=request.get_json(silent=True) or {}; current=str(payload.get('current_password') or ''); new=str(payload.get('new_password') or '')
    if not check_password_hash(worker.get('password_hash') or '',current): return jsonify({'error':'Current password is incorrect'}),400
    if len(new)<8 or not re.search(r'[A-Za-z]',new) or not re.search(r'\d',new):
        return jsonify({'error':'New password must be at least 8 characters and contain a letter and number'}),400
    if not db.update_worker_password(worker['worker_number'],generate_password_hash(new)): return jsonify({'error':'Unable to change password'}),500
    return jsonify({'message':'Password changed'})

@app.route('/api/worker/violations')
@require_worker
def worker_violations(worker):
    return jsonify(db.worker_violations(worker['worker_number'],request.args.get('page'),request.args.get('per_page'),
        request.args.get('status'),request.args.get('ppe')))

@app.route('/api/worker/devices', methods=['POST', 'DELETE'])
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

@app.route('/api/worker/attendance')
@require_worker
def worker_attendance(worker):
    return jsonify(db.worker_attendance(worker['worker_number'],request.args.get('page'),request.args.get('per_page'),
        request.args.get('month'),request.args.get('date')))

@app.route('/api/worker/attendance-requests',methods=['GET','POST'])
@require_worker
def worker_attendance_requests(worker):
    if request.method=='GET': return jsonify(db.worker_attendance_requests(worker['worker_number']))
    payload=request.get_json(silent=True) or {}
    ok,message,request_id=db.create_attendance_request(worker['worker_number'],payload.get('action'),payload.get('requested_at'),payload.get('reason'))
    if not ok: return jsonify({'error':message}),400
    recipients=db.attendance_request_recipients(worker['worker_number'])
    sent=set()
    for recipient in recipients:
        token=recipient.get('expo_push_token')
        if token and token not in sent:
            expo_push_notifier.send_attendance_request(token,request_id,worker['name'],payload.get('action'),payload.get('requested_at')); sent.add(token)
    return jsonify({'message':message,'id':request_id,'notified_supervisors':len({r['supervisor_id'] for r in recipients})}),201

@app.route('/api/worker/violations/<instance_id>/proof', methods=['POST'])
@require_worker
def worker_submit_proof(instance_id, worker):
    payload=request.get_json(silent=True) or {}; image=str(payload.get('image_base64') or ''); comment=str(payload.get('comment') or '').strip()
    if not comment or not image: return jsonify({'error':'Acknowledgement and a new proof photo are required'}),400
    try:
        raw=base64.b64decode(image.split(',',1)[-1], validate=True)
        if len(raw)>8*1024*1024: raise ValueError('Photo is too large')
        proof_dir=os.path.join(BASE_DIR,'worker_proofs'); os.makedirs(proof_dir,exist_ok=True); path=os.path.join(proof_dir,f'{instance_id}_{uuid.uuid4().hex}.jpg'); open(path,'wb').write(raw)
    except Exception: return jsonify({'error':'Proof photo is invalid'}),400
    ok,message=db.submit_worker_proof(worker['worker_number'],instance_id,comment,path)
    if not ok:
        try: os.remove(path)
        except OSError: pass
    return jsonify({'status':'success' if ok else 'error','message':message}),200 if ok else 400


@app.route('/api/mobile/me')
@require_supervisor()
def mobile_me(supervisor):
    return jsonify(supervisor_profile(supervisor))


@app.route('/api/mobile/devices', methods=['POST', 'DELETE'])
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


@app.route('/api/mobile/violations')
@require_supervisor()
def mobile_violations(supervisor):
    return jsonify(db.get_mobile_violations(supervisor['id'], request.args.get('status', 'pending')))

@app.route('/api/mobile/workers')
@require_supervisor()
def mobile_workers(supervisor):
    return jsonify(db.search_active_workers(request.args.get('search', '')))

@app.route('/api/mobile/violations/<instance_id>/assign-worker', methods=['POST'])
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


@app.route('/api/mobile/attendance-requests')
@require_supervisor()
def mobile_attendance_requests(supervisor):
    return jsonify(db.supervisor_attendance_requests(supervisor['id'],request.args.get('status','pending')))


@app.route('/api/mobile/attendance-requests/<int:request_id>/decision',methods=['PATCH'])
@require_supervisor()
def mobile_attendance_request_decision(request_id,supervisor):
    payload=request.get_json(silent=True) or {}
    ok,message=db.decide_attendance_request(supervisor,request_id,payload.get('decision'),payload.get('reason'))
    return jsonify({'status':'success' if ok else 'error','message':message}),200 if ok else 400


@app.route('/api/mobile/notifications/unread-count')
@require_supervisor()
def mobile_unread_notification_count(supervisor):
    return jsonify({'unread_count': db.get_mobile_unread_notification_count(supervisor['id'])})


@app.route('/api/mobile/notifications/read', methods=['POST'])
@require_supervisor()
def mobile_mark_notifications_read(supervisor):
    payload = request.get_json(silent=True) or {}
    ok, updated = db.mark_mobile_notification_read(supervisor['id'], payload.get('instance_id'))
    return jsonify({'status': 'success' if ok else 'error', 'updated': updated}), 200 if ok else 500


@app.route('/api/mobile/notifications/test', methods=['POST'])
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


@app.route('/api/mobile/violations/<instance_id>')
@require_supervisor()
def mobile_violation_detail(instance_id, supervisor):
    data = db.get_mobile_violation_detail(supervisor['id'], instance_id)
    if not data:
        return jsonify({'error': 'Violation not found'}), 404
    for snapshot in data['snapshots']:
        snapshot['url'] = url_for('mobile_snapshot', snapshot_id=snapshot['id'], _external=True)
    if data.get('review_status') == 'worker_submitted':
        data['worker_proof_url'] = url_for('mobile_worker_proof', instance_id=instance_id, _external=True)
    return jsonify(data)

@app.route('/api/mobile/violations/<instance_id>/worker-proof')
@require_supervisor()
def mobile_worker_proof(instance_id, supervisor):
    path=db.get_worker_proof_path(supervisor['id'],instance_id)
    if not path or not os.path.isfile(path): return jsonify({'error':'Worker proof not found'}),404
    return send_file(path,mimetype='image/jpeg')


@app.route('/api/mobile/violations/<instance_id>/review', methods=['PATCH'])
@require_supervisor()
def mobile_update_review(instance_id, supervisor):
    payload = request.get_json(silent=True) or {}
    ok, message = db.update_mobile_review(
        supervisor, instance_id, payload.get('review_status'), payload.get('review_reason')
    )
    return jsonify({'status': 'success' if ok else 'error', 'message': message}), 200 if ok else 400


@app.route('/api/mobile/snapshots/<int:snapshot_id>')
@require_supervisor()
def mobile_snapshot(snapshot_id, supervisor):
    path = db.get_mobile_snapshot_path(supervisor['id'], snapshot_id)
    if not path or not os.path.isfile(path):
        return jsonify({'error': 'Snapshot not found'}), 404
    return send_file(path, mimetype='image/jpeg')


@app.route('/api/admin/supervisors', methods=['GET', 'POST'])
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

@app.route('/api/admin/settings', methods=['GET'])
@require_supervisor(admin_only=True)
def get_settings(supervisor):
    """Get current settings"""
    return jsonify(current_settings)

@app.route('/api/admin/settings', methods=['POST'])
@require_supervisor(admin_only=True)
def update_settings(supervisor):
    """Update settings"""
    global current_settings
    try:
        new_settings = request.json
        current_settings = new_settings
        
        instance_detector.update_settings(new_settings)
        
        if save_settings_to_file(new_settings):
            return jsonify({'status': 'success', 'message': 'Settings saved'})
        else:
            return jsonify({'status': 'error', 'message': 'Failed to save settings to file'}), 500
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/admin/settings/reset', methods=['POST'])
@require_supervisor(admin_only=True)
def reset_settings(supervisor):
    """Reset settings to defaults"""
    global current_settings
    try:
        current_settings = DEFAULT_SETTINGS.copy()
        instance_detector.update_settings(current_settings)
        
        if save_settings_to_file(current_settings):
            return jsonify({'status': 'success', 'message': 'Settings reset to defaults', 'settings': current_settings})
        else:
            return jsonify({'status': 'error', 'message': 'Failed to save settings to file'}), 500
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/admin/workers', methods=['GET'])
@require_supervisor(admin_only=True)
def get_workers(supervisor):
    """List registered workers"""
    return jsonify(db.get_workers(include_inactive=True))

@app.route('/api/admin/workers', methods=['POST'])
@require_supervisor(admin_only=True)
def save_worker(supervisor):
    """Create or update a worker"""
    payload = request.json or {}
    password = str(payload.get('password') or '')
    ok, message = db.save_worker(payload, generate_password_hash(password) if password else None)
    status_code = 200 if ok else 400
    return jsonify({'status': 'success' if ok else 'error', 'message': message}), status_code

@app.route('/api/admin/workers/<worker_number>', methods=['DELETE'])
@require_supervisor(admin_only=True)
def delete_worker(worker_number, supervisor):
    """Delete a worker from the registry"""
    if db.delete_worker(worker_number):
        return jsonify({'status': 'success', 'message': 'Worker deleted'})
    return jsonify({'status': 'error', 'message': 'Failed to delete worker'}), 500


@app.route('/api/admin/attendance', methods=['GET', 'POST'])
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

@app.route('/video_feed')
def video_feed():
    """Video streaming route"""
    try:
        return Response(generate_frames(),
                        mimetype='multipart/x-mixed-replace; boundary=frame')
    except Exception as e:
        print(f"Error in video_feed: {e}")
        return '', 500

@app.route('/start_stream', methods=['POST'])
def start_stream():
    """Start video streaming"""
    global camera, streaming, model
    
    try:
        if model is None:
            load_model()
        
        with stream_lock:
            if camera is None or not camera.isOpened():
                camera = cv2.VideoCapture(0)
                camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        
        streaming = True
        return jsonify({'status': 'success', 'message': 'Stream started'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/stop_stream', methods=['POST'])
def stop_stream():
    """Stop video streaming"""
    global camera, streaming
    
    try:
        streaming = False
        time.sleep(0.3)
        
        with stream_lock:
            if camera is not None:
                camera.release()
                camera = None
        
        return jsonify({'status': 'success', 'message': 'Stream stopped'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/toggle_dev_mode', methods=['POST'])
def toggle_dev_mode():
    """Toggle dev/testing mode"""
    global dev_mode
    dev_mode = not dev_mode
    return jsonify({'status': 'success', 'dev_mode': dev_mode, 
                   'message': f'Dev mode {"enabled" if dev_mode else "disabled"}'})

@app.route('/stats')
def get_stats():
    """Get detection statistics"""
    stats = db.get_statistics()
    stats['dev_mode'] = dev_mode
    return jsonify(stats)

@app.route('/api/admin/instances')
@require_supervisor(admin_only=True)
def get_instances(supervisor):
    """Get all detection instances"""
    try:
        sort_by = request.args.get('sort', 'first_detected')
        sort_order = request.args.get('order', 'desc')
        status = request.args.get('status')
        
        instances = db.get_all_instances(sort_by, sort_order, status)
        return jsonify(instances)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/detection-analysis')
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

@app.route('/api/admin/instances/<instance_id>/review', methods=['PATCH'])
@require_supervisor(admin_only=True)
def update_instance_review(instance_id, supervisor):
    """Update review status and reason for a violation instance"""
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

@app.route('/api/admin/instances/<instance_id>/snapshots')
@require_supervisor(admin_only=True)
def get_instance_snapshots(instance_id, supervisor):
    """Get all snapshots for a specific instance"""
    try:
        data = db.get_instance_snapshots(instance_id)
        if data:
            return jsonify(data)
        return jsonify({'error': 'Instance not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/download_snapshot/<path:filename>')
def download_snapshot(filename):
    """Download snapshot"""
    try:
        filepath = filename if os.path.isabs(filename) else os.path.join('snapshots', filename)
        if os.path.exists(filepath):
            return send_file(filepath, as_attachment=True)
        return jsonify({'error': 'File not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/snapshots/<path:filename>')
def serve_snapshot(filename):
    """Serve snapshot for viewing"""
    try:
        filepath = os.path.join('snapshots', filename)
        if os.path.exists(filepath):
            return send_file(filepath, mimetype='image/jpeg')
        return jsonify({'error': 'File not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/instances/<instance_id>', methods=['DELETE'])
@require_supervisor(admin_only=True)
def delete_instance(instance_id, supervisor):
    """Delete an instance and its snapshot"""
    try:
        success = db.delete_instance(instance_id)
        if success:
            return jsonify({'status': 'success', 'message': 'Instance deleted'})
        return jsonify({'error': 'Failed to delete instance'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
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
        instance_detector.update_settings(current_settings)
        socketio.run(
            app,
            debug=os.getenv('FLASK_DEBUG', 'true').strip().lower() == 'true',
            host=os.getenv('FLASK_HOST', '0.0.0.0'),
            port=int(os.getenv('FLASK_PORT', '3333')),
        )
    except Exception as e:
        print(f"Fatal error starting app: {e}")

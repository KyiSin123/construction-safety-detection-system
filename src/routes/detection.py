"""Local camera capture + YOLO inference: live video feed, snapshot storage, dev-mode toggle.

These routes assume a physical camera is attached to whatever machine runs this
process -- they are not usable from a typical cloud host with no camera hardware.
"""

import os
import threading
import time
from datetime import datetime

import cv2
from flask import Blueprint, Response, jsonify, send_file

import extensions
from extensions import (
    compliance_checker, db, identity_reader, instance_detector,
    send_mobile_supervisor_notifications, snapshot_manager, socketio,
)
from identity_service import ViolationCropBuffer, select_worker_crop

detection_bp = Blueprint('detection', __name__)

model = None
camera = None
streaming = False
stream_lock = threading.Lock()
dev_mode = False


def load_model():
    """Load the shared YOLO model (also used by the upload-analysis endpoints)."""
    global model
    model = extensions.get_model()


def hide_classes_for_display(result):
    """Return a result copy without classes that should not be drawn."""
    if result.boxes is None:
        return result

    keep_indices = [
        i for i, cls in enumerate(result.boxes.cls)
        if model.names[int(cls)] not in extensions.HIDDEN_DISPLAY_CLASSES
    ]
    return result[keep_indices]


def generate_frames():
    """Generate video frames with instance detection."""
    global camera, streaming, model

    last_alert_time = 0
    ALERT_COOLDOWN = extensions.current_settings['non_compliance_delay']
    last_snapshot_time = 0
    SNAPSHOT_INTERVAL = extensions.current_settings['instance_reset_timeout']
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

            instance_result = instance_detector.process_detection(all_detections, dev_mode, extensions.current_settings)
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


@detection_bp.route('/video_feed')
def video_feed():
    """Video streaming route."""
    try:
        return Response(generate_frames(),
                        mimetype='multipart/x-mixed-replace; boundary=frame')
    except Exception as e:
        print(f"Error in video_feed: {e}")
        return '', 500


@detection_bp.route('/start_stream', methods=['POST'])
def start_stream():
    """Start video streaming."""
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


@detection_bp.route('/stop_stream', methods=['POST'])
def stop_stream():
    """Stop video streaming."""
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


@detection_bp.route('/toggle_dev_mode', methods=['POST'])
def toggle_dev_mode():
    """Toggle dev/testing mode."""
    global dev_mode
    dev_mode = not dev_mode
    return jsonify({'status': 'success', 'dev_mode': dev_mode,
                   'message': f'Dev mode {"enabled" if dev_mode else "disabled"}'})


@detection_bp.route('/stats')
def get_stats():
    """Get detection statistics."""
    stats = db.get_statistics()
    stats['dev_mode'] = dev_mode
    return jsonify(stats)


@detection_bp.route('/download_snapshot/<path:filename>')
def download_snapshot(filename):
    """Download snapshot."""
    try:
        filepath = filename if os.path.isabs(filename) else os.path.join('snapshots', filename)
        if os.path.exists(filepath):
            return send_file(filepath, as_attachment=True)
        return jsonify({'error': 'File not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@detection_bp.route('/snapshots/<path:filename>')
def serve_snapshot(filename):
    """Serve snapshot for viewing."""
    try:
        filepath = os.path.join('snapshots', filename)
        if os.path.exists(filepath):
            return send_file(filepath, mimetype='image/jpeg')
        return jsonify({'error': 'File not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

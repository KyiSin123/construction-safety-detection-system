"""Uploaded image/video PPE analysis with batch-aware operational alerts."""

import base64
import os
import tempfile
import time
import uuid
from datetime import datetime

import cv2
import numpy as np
from flask import Blueprint, jsonify, request

import extensions
from identity_service import crop_bbox

video_analysis_bp = Blueprint('video_analysis', __name__)

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_VIDEO_SECONDS = 60
SAMPLE_FPS = 2
MAX_FRAME_WIDTH = 960
TRACK_MAX_GAP = SAMPLE_FPS * 3

PPE_CLASS_MAPPING = {
    'helmet': {'positive': {'helmet', 'hardhat', 'hard-hat', 'hard hat'},
               'negative': {'no-hardhat', 'no-helmet'}},
    'vest': {'positive': {'vest', 'safety-vest', 'safety vest'},
             'negative': {'no-vest'}},
    'mask': {'positive': {'mask', 'face mask', 'face-mask', 'respirator'},
             'negative': {'no-mask', 'no-face-mask'}},
}


def _resize_if_needed(frame):
    height, width = frame.shape[:2]
    if width <= MAX_FRAME_WIDTH:
        return frame
    scale = MAX_FRAME_WIDTH / width
    return cv2.resize(frame, (MAX_FRAME_WIDTH, int(height * scale)))


def _detect(model, frame):
    result = model(frame)[0]
    detections = []
    for box in result.boxes:
        x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
        detections.append({
            'class': str(model.names[int(box.cls[0])]).lower(),
            'confidence': float(box.conf[0]),
            'bbox': [int(x1), int(y1), int(x2), int(y2)],
        })
    return detections, result


def _center_inside(item_bbox, person_bbox):
    x1, y1, x2, y2 = item_bbox
    px1, py1, px2, py2 = person_bbox
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    padding_x = (px2 - px1) * 0.08
    padding_y = (py2 - py1) * 0.08
    return (
        px1 - padding_x <= cx <= px2 + padding_x
        and py1 - padding_y <= cy <= py2 + padding_y
    )


def _person_candidates(frame, detections):
    """Return one independently evaluated candidate for every detected person."""
    required = extensions.current_settings.get('required_ppe', {})
    people = [item for item in detections if item['class'] == 'person']
    equipment = [item for item in detections if item['class'] != 'person']
    candidates = []

    for person in people:
        associated = [
            item for item in equipment
            if _center_inside(item['bbox'], person['bbox'])
        ]
        classes = {item['class'] for item in associated}
        missing = []
        detected = []
        for ppe_type, is_required in required.items():
            if not is_required:
                continue
            mapping = PPE_CLASS_MAPPING.get(
                ppe_type,
                {'positive': {ppe_type}, 'negative': {f'no-{ppe_type}'}},
            )
            has_positive = bool(classes & mapping['positive'])
            has_negative = bool(classes & mapping['negative'])
            if has_negative or not has_positive:
                missing.append(ppe_type)
            else:
                detected.append(ppe_type)

        crop = crop_bbox(frame, person['bbox'], padding=0.14)
        candidates.append({
            'bbox': person['bbox'],
            'missing_ppe': missing,
            'detected_ppe': detected,
            'crop': crop,
            'sharpness': _sharpness(crop),
        })
    return candidates


def _sharpness(crop):
    if crop is None or crop.size == 0:
        return 0
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _encode_jpeg(frame):
    if frame is None or frame.size == 0:
        return None
    ok, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return base64.b64encode(buffer).decode('ascii') if ok else None


def _iou(first, second):
    x1 = max(first[0], second[0])
    y1 = max(first[1], second[1])
    x2 = min(first[2], second[2])
    y2 = min(first[3], second[3])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    first_area = max(0, first[2] - first[0]) * max(0, first[3] - first[1])
    second_area = max(0, second[2] - second[0]) * max(0, second[3] - second[1])
    union = first_area + second_area - intersection
    return intersection / union if union else 0


def _update_tracks(tracks, candidates, analyzed_index, video_seconds):
    unmatched_tracks = {
        index for index, track in enumerate(tracks)
        if analyzed_index - track['last_seen_frame'] <= TRACK_MAX_GAP
    }
    for candidate in candidates:
        if not candidate['missing_ppe']:
            continue
        possible = [
            (index, _iou(tracks[index]['bbox'], candidate['bbox']))
            for index in unmatched_tracks
        ]
        best_index, best_iou = max(possible, key=lambda pair: pair[1], default=(None, 0))
        if best_index is None or best_iou < 0.25:
            tracks.append({
                **candidate,
                'start_seconds': round(video_seconds, 1),
                'end_seconds': round(video_seconds, 1),
                'last_seen_frame': analyzed_index,
            })
            continue

        track = tracks[best_index]
        unmatched_tracks.remove(best_index)
        track['bbox'] = candidate['bbox']
        track['last_seen_frame'] = analyzed_index
        track['end_seconds'] = round(video_seconds, 1)
        track['missing_ppe'] = sorted(
            set(track['missing_ppe']) | set(candidate['missing_ppe'])
        )
        track['detected_ppe'] = sorted(
            set(track['detected_ppe']) | set(candidate['detected_ppe'])
        )
        if candidate['sharpness'] > track['sharpness']:
            track['crop'] = candidate['crop']
            track['sharpness'] = candidate['sharpness']


def _instance_id(batch_id, index):
    return f"TRY_{datetime.now().strftime('%m_%d_%Y')}_{batch_id[:8]}_{index + 1}"


def _persist_alerts(candidates, batch_id):
    """Identify all people, claim the unknown batch once, then persist each accepted person."""
    alerts = []
    identified = []
    for candidate in candidates:
        identity = extensions.identity_reader.identify_worker(
            candidate['crop'], extensions.db
        ).to_dict()
        identified.append((candidate, identity))

    has_unknown = any(
        identity.get('identity_status') != 'confirmed'
        or not identity.get('worker_number')
        for _, identity in identified
    )
    unknown_batch_allowed = (
        extensions.db.claim_unknown_alert_batch(batch_id) if has_unknown else False
    )

    for index, (candidate, identity) in enumerate(identified):
        instance_id = _instance_id(batch_id, index)
        unknown = (
            identity.get('identity_status') != 'confirmed'
            or not identity.get('worker_number')
        )
        result = {
            'instance_id': instance_id,
            'identity': identity,
            'missing_ppe': candidate['missing_ppe'],
            'detected_ppe': candidate['detected_ppe'],
            'alert_priority': (
                1 if unknown else 2 if 'helmet' in candidate['missing_ppe'] else 3
            ),
            'snapshot_base64': _encode_jpeg(candidate['crop']),
            'notifications': [],
        }

        blocker = None
        if unknown:
            if not unknown_batch_allowed:
                blocker = extensions.db.find_blocking_violation(
                    candidate['missing_ppe'], identity, batch_id
                ) or 'unknown-alert-batch-already-claimed'
        else:
            blocker = extensions.db.find_blocking_violation(
                candidate['missing_ppe'], identity, batch_id
            )

        if blocker:
            result.update(status='duplicate_skipped', existing_instance_id=blocker)
            alerts.append(result)
            continue

        snapshot_path = extensions.snapshot_manager.save_snapshot(
            candidate['crop'], f'{instance_id}_snapshot_1'
        )
        if not snapshot_path:
            result.update(status='delivery_failed', error='Could not save violation snapshot')
            alerts.append(result)
            continue

        logged = extensions.db.log_instance_snapshot(
            instance_id=instance_id,
            missing_ppe=candidate['missing_ppe'],
            detected_ppe=candidate['detected_ppe'],
            snapshot_path=snapshot_path,
            identity=identity,
            detection_batch_id=batch_id,
        )
        if not logged:
            result.update(status='delivery_failed', error='Could not store violation')
            alerts.append(result)
            continue

        notifications = extensions.send_mobile_supervisor_notifications(
            instance_id, candidate['missing_ppe'], identity
        )
        result['notifications'] = notifications
        delivered = bool(notifications) and all(
            item['status'] == 'sent' for item in notifications
        )
        result['status'] = 'alerted' if delivered else 'delivery_failed'
        if not delivered:
            result['error'] = 'One or more supervisor notifications were not delivered'
        alerts.append(result)
    return alerts


@video_analysis_bp.route('/api/analyze/image', methods=['POST'])
def analyze_image():
    upload = request.files.get('image')
    if not upload:
        return jsonify({'error': 'Attach an image file as "image"'}), 400
    raw = upload.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        return jsonify({'error': 'Image is too large (50MB limit)'}), 400

    frame = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        return jsonify({'error': 'Could not read this image'}), 400
    frame = _resize_if_needed(frame)

    model = extensions.get_model()
    detections, plotted_result = _detect(model, frame)
    people = _person_candidates(frame, detections)
    violations = [person for person in people if person['missing_ppe']]
    batch_id = uuid.uuid4().hex
    alerts = _persist_alerts(violations, batch_id) if violations else []

    return jsonify({
        'detection_batch_id': batch_id,
        'has_person': bool(people),
        'person_count': len(people),
        'non_compliant_count': len(violations),
        'is_compliant': not violations,
        'missing_ppe': sorted({
            item for person in violations for item in person['missing_ppe']
        }),
        'detected_classes': sorted({item['class'] for item in detections}),
        'annotated_image_base64': _encode_jpeg(plotted_result.plot()),
        'alerts': alerts,
    })


@video_analysis_bp.route('/api/analyze/video', methods=['POST'])
def analyze_video():
    upload = request.files.get('video')
    if not upload:
        return jsonify({'error': 'Attach a video file as "video"'}), 400

    tmp_path = None
    capture = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
            tmp_path = tmp.name
            written = 0
            while True:
                chunk = upload.stream.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    return jsonify({'error': 'Video is too large (50MB limit)'}), 400
                tmp.write(chunk)

        capture = cv2.VideoCapture(tmp_path)
        if not capture.isOpened():
            return jsonify({'error': 'Could not read this video file'}), 400

        source_fps = capture.get(cv2.CAP_PROP_FPS) or 30
        frame_stride = max(1, round(source_fps / SAMPLE_FPS))
        model = extensions.get_model()
        tracks = []
        frame_index = 0
        analyzed_count = 0
        start_time = time.time()

        while True:
            success, frame = capture.read()
            if not success:
                break
            frame_index += 1
            if frame_index % frame_stride != 0:
                continue
            video_seconds = frame_index / source_fps
            if video_seconds > MAX_VIDEO_SECONDS:
                break

            frame = _resize_if_needed(frame)
            detections, _ = _detect(model, frame)
            analyzed_count += 1
            _update_tracks(
                tracks,
                _person_candidates(frame, detections),
                analyzed_count,
                video_seconds,
            )

        batch_id = uuid.uuid4().hex
        alerts = _persist_alerts(tracks, batch_id) if tracks else []
        events = [
            {
                'start_seconds': track['start_seconds'],
                'end_seconds': track['end_seconds'],
                'missing_ppe': track['missing_ppe'],
                'snapshot_base64': _encode_jpeg(track['crop']),
            }
            for track in tracks
        ]
        return jsonify({
            'detection_batch_id': batch_id,
            'analyzed_frames': analyzed_count,
            'sample_fps': SAMPLE_FPS,
            'processing_seconds': round(time.time() - start_time, 1),
            'person_violation_count': len(tracks),
            'violation_events': events,
            'alerts': alerts,
            'is_compliant': not tracks,
        })
    finally:
        if capture is not None:
            capture.release()
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

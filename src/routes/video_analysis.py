"""Stateless PPE-compliance analysis for an uploaded image or video clip.

Unlike routes/detection.py (which assumes a physical camera and persists violations to the
shared database), these endpoints run the same YOLO model against an uploaded file and return
everything in the response. Nothing is written to disk or to the violations table, which makes
this safe to expose as a public "try it out" demo without polluting real monitoring data --
this is the endpoint a cloud deployment with no camera attached would use.
"""

import base64
import os
import tempfile
import time

import cv2
import numpy as np
from flask import Blueprint, jsonify, request

import extensions

video_analysis_bp = Blueprint('video_analysis', __name__)

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_VIDEO_SECONDS = 60
SAMPLE_FPS = 2
MAX_FRAME_WIDTH = 960

PPE_CLASS_MAPPING = {
    'helmet': ['helmet', 'hardhat', 'hard-hat', 'hard hat'],
    'vest': ['vest', 'safety-vest', 'safety vest'],
    'mask': ['mask', 'face mask', 'face-mask', 'respirator'],
}


def _resize_if_needed(frame):
    height, width = frame.shape[:2]
    if width <= MAX_FRAME_WIDTH:
        return frame
    scale = MAX_FRAME_WIDTH / width
    return cv2.resize(frame, (MAX_FRAME_WIDTH, int(height * scale)))


def _detect(model, frame):
    results = model(frame)
    detected_classes = [
        str(model.names[int(box.cls[0])]).lower()
        for result in results
        for box in result.boxes
    ]
    return detected_classes, results[0]


def _missing_ppe(detected_classes):
    required_ppe = extensions.current_settings.get('required_ppe', {})
    missing = []
    for ppe_type, is_required in required_ppe.items():
        if not is_required:
            continue
        class_names = PPE_CLASS_MAPPING.get(ppe_type, [ppe_type])
        if not any(name in detected_classes for name in class_names):
            missing.append(ppe_type)
    return missing


def _encode_jpeg(frame):
    ok, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return base64.b64encode(buffer).decode('ascii') if ok else None


@video_analysis_bp.route('/api/analyze/image', methods=['POST'])
def analyze_image():
    """Run one uploaded image through the PPE model and return the compliance result."""
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
    detected_classes, plotted_result = _detect(model, frame)
    has_person = 'person' in detected_classes
    missing_ppe = _missing_ppe(detected_classes) if has_person else []

    return jsonify({
        'has_person': has_person,
        'is_compliant': not missing_ppe,
        'missing_ppe': missing_ppe,
        'detected_classes': sorted(set(detected_classes)),
        'annotated_image_base64': _encode_jpeg(plotted_result.plot()),
    })


@video_analysis_bp.route('/api/analyze/video', methods=['POST'])
def analyze_video():
    """Sample frames from an uploaded video clip and report PPE-compliance events found in it."""
    upload = request.files.get('video')
    if not upload:
        return jsonify({'error': 'Attach a video file as "video"'}), 400

    tmp_path = None
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
        events = []
        active_event = None
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
            detected_classes, plotted_result = _detect(model, frame)
            analyzed_count += 1
            has_person = 'person' in detected_classes
            missing_ppe = _missing_ppe(detected_classes) if has_person else []

            if missing_ppe:
                if active_event is None:
                    active_event = {
                        'start_seconds': round(video_seconds, 1),
                        'end_seconds': round(video_seconds, 1),
                        'missing_ppe': missing_ppe,
                        'snapshot_base64': _encode_jpeg(plotted_result.plot()),
                    }
                    events.append(active_event)
                else:
                    active_event['end_seconds'] = round(video_seconds, 1)
                    active_event['missing_ppe'] = sorted(set(active_event['missing_ppe']) | set(missing_ppe))
            else:
                active_event = None

        capture.release()

        return jsonify({
            'analyzed_frames': analyzed_count,
            'sample_fps': SAMPLE_FPS,
            'processing_seconds': round(time.time() - start_time, 1),
            'violation_events': events,
            'is_compliant': not events,
        })
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

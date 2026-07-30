import base64
import json
import os
import re
from dataclasses import dataclass

import cv2


@dataclass
class IdentityResult:
    worker_number: str | None = None
    worker_name: str | None = None
    team: str | None = None
    identity_confidence: float = 0.0
    identity_status: str = 'unknown'
    identity_source: str = 'openai_vision'
    visible_location: str | None = None
    raw_response: str | None = None
    error: str | None = None

    def to_dict(self):
        return {
            'worker_number': self.worker_number,
            'worker_name': self.worker_name,
            'team': self.team,
            'identity_confidence': self.identity_confidence,
            'identity_status': self.identity_status,
            'identity_source': self.identity_source,
            'visible_location': self.visible_location,
            'raw_response': self.raw_response,
            'error': self.error,
        }


class WorkerIdentityReader:
    """Reads worker uniform numbers from cropped violation images."""

    def __init__(self, confidence_threshold=0.75):
        self.confidence_threshold = confidence_threshold
        self.model = os.getenv('OPENAI_VISION_MODEL', 'gpt-4o-mini')
        self.enabled = bool(os.getenv('OPENAI_API_KEY'))
        self.client = None

        if self.enabled:
            try:
                from openai import OpenAI
                self.client = OpenAI()
            except Exception as e:
                self.enabled = False
                print(f"[Identity] OpenAI client unavailable: {e}")

    def identify_worker(self, crop, db):
        if crop is None or crop.size == 0:
            return IdentityResult(identity_status='unknown', error='Empty worker crop')

        if not self.enabled or self.client is None:
            return IdentityResult(
                identity_status='pending_review',
                error='OPENAI_API_KEY is not configured'
            )

        try:
            image_data = self._encode_crop(crop)
            prompt = (
                "Read the worker identification number printed on this construction worker's "
                "uniform, vest, helmet, sleeve, chest, or back. Return only JSON with keys: "
                "worker_number string or null, confidence number from 0 to 1, "
                "visible_location string, unclear boolean, notes string. "
                "If the number is not clearly readable, set worker_number to null and unclear to true."
            )

            response = self.client.responses.create(
                model=self.model,
                input=[{
                    'role': 'user',
                    'content': [
                        {'type': 'input_text', 'text': prompt},
                        {'type': 'input_image', 'image_url': f'data:image/jpeg;base64,{image_data}'},
                    ],
                }],
            )

            raw_text = getattr(response, 'output_text', '') or ''
            parsed = self._parse_json(raw_text)
            worker_number = self._normalize_worker_number(parsed.get('worker_number'))
            confidence = self._safe_float(parsed.get('confidence'))
            unclear = bool(parsed.get('unclear'))

            result = IdentityResult(
                worker_number=worker_number,
                identity_confidence=confidence,
                visible_location=parsed.get('visible_location'),
                raw_response=raw_text,
            )

            if unclear or not worker_number:
                result.identity_status = 'pending_review'
                return result

            worker = db.get_worker_by_number(worker_number)
            if not worker:
                result.identity_status = 'unregistered'
                return result

            result.worker_name = worker.get('name')
            result.team = worker.get('team')
            result.identity_status = (
                'confirmed' if confidence >= self.confidence_threshold else 'low_confidence'
            )
            return result
        except Exception as e:
            return IdentityResult(identity_status='pending_review', error=str(e))

    def _encode_crop(self, crop):
        max_width = 900
        height, width = crop.shape[:2]
        if width > max_width:
            scale = max_width / width
            crop = cv2.resize(crop, (max_width, int(height * scale)))

        ok, buffer = cv2.imencode('.jpg', crop, [cv2.IMWRITE_JPEG_QUALITY, 88])
        if not ok:
            raise ValueError('Could not encode worker crop')
        return base64.b64encode(buffer).decode('utf-8')

    def _parse_json(self, text):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
        return {}

    def _normalize_worker_number(self, value):
        if value is None:
            return None
        value = str(value).strip().upper()
        value = re.sub(r'[^A-Z0-9_-]', '', value)
        return value or None

    def _safe_float(self, value):
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return 0.0


class ViolationCropBuffer:
    """Keeps recent worker crops and returns the clearest crop for identity reading."""

    def __init__(self, max_size=8):
        self.max_size = max_size
        self.crops = []

    def add(self, crop):
        if crop is None or crop.size == 0:
            return
        self.crops.append((self._sharpness(crop), crop.copy()))
        if len(self.crops) > self.max_size:
            self.crops = self.crops[-self.max_size:]

    def best(self):
        if not self.crops:
            return None
        return max(self.crops, key=lambda item: item[0])[1]

    def clear(self):
        self.crops.clear()

    def _sharpness(self, crop):
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        return cv2.Laplacian(gray, cv2.CV_64F).var()


def select_worker_crop(frame, detections):
    """Choose the person crop most likely related to a helmet violation."""
    persons = [d for d in detections if d['class'].lower() == 'person']
    no_helmet = [
        d for d in detections
        if d['class'].lower() in {'no-hardhat', 'no-helmet'}
    ]

    if not persons:
        return None

    selected = None
    if no_helmet:
        helmet_box = no_helmet[0]['bbox']
        hx = (helmet_box[0] + helmet_box[2]) / 2
        hy = (helmet_box[1] + helmet_box[3]) / 2
        containing = [
            p for p in persons
            if p['bbox'][0] <= hx <= p['bbox'][2] and p['bbox'][1] <= hy <= p['bbox'][3]
        ]
        selected = containing[0] if containing else _largest_box(persons)
    else:
        selected = _largest_box(persons)

    return crop_bbox(frame, selected['bbox'], padding=0.14)


def crop_bbox(frame, bbox, padding=0.1):
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = bbox
    pad_x = int((x2 - x1) * padding)
    pad_y = int((y2 - y1) * padding)
    x1 = max(0, x1 - pad_x)
    y1 = max(0, y1 - pad_y)
    x2 = min(width, x2 + pad_x)
    y2 = min(height, y2 + pad_y)
    return frame[y1:y2, x1:x2].copy()


def _largest_box(detections):
    return max(
        detections,
        key=lambda d: max(0, d['bbox'][2] - d['bbox'][0]) * max(0, d['bbox'][3] - d['bbox'][1])
    )

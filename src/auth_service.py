"""Minimal HS256 JWT helpers for the supervisor mobile API."""

import base64
import hashlib
import hmac
import json
import os
import time


class AuthService:
    def __init__(self):
        self.secret = os.getenv('SUPERVISOR_JWT_SECRET', '')
        self.ttl_seconds = int(os.getenv('SUPERVISOR_JWT_TTL_SECONDS', '28800'))

    @property
    def configured(self):
        return len(self.secret) >= 32

    @staticmethod
    def _encode(value):
        return base64.urlsafe_b64encode(value).rstrip(b'=').decode('ascii')

    @staticmethod
    def _decode(value):
        return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))

    def issue_token(self, supervisor):
        if not self.configured:
            raise RuntimeError('SUPERVISOR_JWT_SECRET must be configured with at least 32 characters')
        now = int(time.time())
        header = self._encode(json.dumps({'alg': 'HS256', 'typ': 'JWT'}, separators=(',', ':')).encode())
        payload = self._encode(json.dumps({
            'sub': supervisor['id'],
            'username': supervisor['username'],
            'role': supervisor['role'],
            'iat': now,
            'exp': now + self.ttl_seconds,
        }, separators=(',', ':')).encode())
        signature = hmac.new(self.secret.encode(), f'{header}.{payload}'.encode(), hashlib.sha256).digest()
        return f'{header}.{payload}.{self._encode(signature)}'

    def issue_worker_token(self, worker):
        if not self.configured:
            raise RuntimeError('SUPERVISOR_JWT_SECRET must be configured with at least 32 characters')
        now = int(time.time())
        header = self._encode(json.dumps({'alg': 'HS256', 'typ': 'JWT'}, separators=(',', ':')).encode())
        payload = self._encode(json.dumps({'sub': worker['worker_number'], 'account_type': 'worker', 'iat': now, 'exp': now + self.ttl_seconds}, separators=(',', ':')).encode())
        signature = hmac.new(self.secret.encode(), f'{header}.{payload}'.encode(), hashlib.sha256).digest()
        return f'{header}.{payload}.{self._encode(signature)}'

    def verify_token(self, token):
        if not self.configured or not token:
            return None
        try:
            header, payload, signature = token.split('.')
            expected = hmac.new(self.secret.encode(), f'{header}.{payload}'.encode(), hashlib.sha256).digest()
            if not hmac.compare_digest(expected, self._decode(signature)):
                return None
            claims = json.loads(self._decode(payload))
            if int(claims.get('exp', 0)) < int(time.time()):
                return None
            return claims
        except (ValueError, TypeError, json.JSONDecodeError):
            return None

"""Expo push delivery for assigned supervisors."""

import requests


class ExpoPushNotifier:
    PUSH_URL = 'https://exp.host/--/api/v2/push/send'

    def send_violation(
        self, expo_push_token, instance_id, worker_name, missing_ppe,
        identity_status='unknown', worker_number=None,
    ):
        is_no_id = identity_status != 'confirmed' or not worker_number
        if is_no_id:
            title = 'URGENT: No ID person detected'
            body = 'Unknown person on site. A supervisor must check this person immediately.'
            priority = 1
        elif 'helmet' in {str(item).strip().lower() for item in missing_ppe}:
            title = 'Helmet safety alert'
            body = f'{worker_name or worker_number}: not wearing a helmet'
            priority = 2
        else:
            title = 'PPE safety alert'
            body = f'{worker_name or worker_number}: missing {", ".join(missing_ppe) or "required PPE"}'
            priority = 3
        return self.send(
            expo_push_token,
            title,
            body,
            {'instance_id': instance_id, 'alert_priority': priority, 'no_id': is_no_id},
        )

    def send_test(self, expo_push_token):
        return self.send(
            expo_push_token,
            'PPE Supervisor test',
            'Push notifications are connected for this device.',
            {'type': 'test'},
        )

    def send_attendance_request(self, expo_push_token, request_id, worker_name, action, requested_at):
        return self.send(
            expo_push_token,
            'Attendance correction requested',
            f'{worker_name}: {action.replace("_", " ")} for {requested_at}',
            {'type': 'attendance_request', 'request_id': request_id},
        )

    def send_worker_violation(self, expo_push_token, instance_id, missing_ppe):
        missing = ', '.join(missing_ppe) or 'required PPE'
        return self.send(
            expo_push_token,
            'Safety action required',
            f'You were identified in a safety alert: missing {missing}. Open the app to respond.',
            {'type': 'worker_violation', 'instance_id': instance_id},
        )

    def send(self, expo_push_token, title, body, data):
        if not expo_push_token:
            return {'status': 'skipped', 'error': 'No registered mobile device'}
        try:
            response = requests.post(
                self.PUSH_URL,
                json={
                    'to': expo_push_token,
                    'title': title,
                    'body': body,
                    'sound': 'default',
                    'priority': 'high',
                    # Android 8+ applies sound/vibration from this named channel.
                    'channelId': 'safety-alerts',
                    'data': data,
                },
                timeout=8,
            )
            if 200 <= response.status_code < 300:
                payload = response.json()
                ticket = (payload.get('data') or [{}])[0]
                if ticket.get('status') == 'ok':
                    return {'status': 'sent', 'error': None}
                return {
                    'status': 'failed',
                    'error': ticket.get('message') or ticket.get('details', {}).get('error') or 'Expo rejected the notification',
                }
            return {'status': 'failed', 'error': f'{response.status_code}: {response.text[:300]}'}
        except Exception as error:
            return {'status': 'failed', 'error': str(error)}

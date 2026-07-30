"""Worker registry, devices, and worker-facing violation/profile actions."""

from .base import REVIEW_STATUSES


class WorkerMixin:
    """Worker CRUD, device registration, and worker-facing profile/violation actions."""

    def register_worker_device(self, worker_number, expo_push_token, platform=None):
        try:
            conn = self._connect()
            c = conn.cursor()
            c.execute('''
                INSERT INTO worker_devices (worker_number, expo_push_token, platform, is_active)
                VALUES (%s, %s, %s, 1)
                ON DUPLICATE KEY UPDATE worker_number = VALUES(worker_number), platform = VALUES(platform),
                    is_active = 1, last_seen_at = CURRENT_TIMESTAMP
            ''', (worker_number, expo_push_token, platform))
            conn.commit()
            c.close()
            conn.close()
            return True, 'Worker device registered'
        except Exception as e:
            print(f"Error registering worker device: {e}")
            return False, str(e)

    def deactivate_worker_device(self, worker_number, expo_push_token=None):
        try:
            conn = self._connect()
            c = conn.cursor()
            query = 'UPDATE worker_devices SET is_active = 0 WHERE worker_number = %s'
            params = [worker_number]
            if expo_push_token:
                query += ' AND expo_push_token = %s'
                params.append(expo_push_token)
            c.execute(query, tuple(params))
            conn.commit()
            c.close()
            conn.close()
            return True
        except Exception as e:
            print(f"Error deactivating worker device: {e}")
            return False

    def search_active_workers(self, search=''):
        try:
            search = str(search or '').strip()
            conn = self._connect()
            c = conn.cursor()
            if search:
                like = f'%{search}%'
                c.execute('''
                    SELECT worker_number, name, team FROM workers
                    WHERE is_active = 1 AND
                        (worker_number LIKE %s OR name LIKE %s OR COALESCE(team, '') LIKE %s)
                    ORDER BY name, worker_number LIMIT 50
                ''', (like, like, like))
            else:
                c.execute('''
                    SELECT worker_number, name, team FROM workers
                    WHERE is_active = 1 ORDER BY name, worker_number LIMIT 50
                ''')
            rows = c.fetchall()
            c.close()
            conn.close()
            return [{'worker_number': row[0], 'name': row[1], 'team': row[2]} for row in rows]
        except Exception as e:
            print(f"Error searching workers: {e}")
            return []

    def get_workers(self, include_inactive=True):
        try:
            conn = self._connect()
            c = conn.cursor()
            query = '''
                SELECT id, worker_number, name, team, is_active, created_at, updated_at
                FROM workers
            '''
            if not include_inactive:
                query += ' WHERE is_active = 1'
            query += ' ORDER BY worker_number ASC'
            c.execute(query)
            rows = c.fetchall()
            c.close()
            conn.close()
            return [self._worker_from_row(row) for row in rows]
        except Exception as e:
            print(f"Error getting workers: {e}")
            return []

    def get_worker_by_number(self, worker_number):
        try:
            conn = self._connect()
            c = conn.cursor()
            c.execute('''
                SELECT id, worker_number, name, team, is_active, created_at, updated_at
                FROM workers
                WHERE worker_number = %s AND is_active = 1
            ''', (worker_number,))
            row = c.fetchone()
            c.close()
            conn.close()
            return self._worker_from_row(row) if row else None
        except Exception as e:
            print(f"Error getting worker: {e}")
            return None

    def get_worker_for_login(self, worker_number):
        try:
            conn = self._connect()
            c = conn.cursor()
            c.execute('''
                SELECT worker_number, name, team, password_hash, is_active, phone, email, profile_photo_path
                FROM workers WHERE worker_number = %s
            ''', (str(worker_number or '').strip().upper(),))
            row = c.fetchone()
            c.close()
            conn.close()
            if not row:
                return None
            return {
                'worker_number': row[0], 'name': row[1], 'team': row[2], 'password_hash': row[3],
                'is_active': bool(row[4]), 'phone': row[5], 'email': row[6],
                'profile_photo_path': row[7],
            }
        except Exception as e:
            print(f"Error getting worker login: {e}")
            return None

    def worker_violations(self, worker_number, page=1, per_page=20, status=None, ppe=None):
        try:
            page, per_page = self._page_values(page, per_page)
            clauses = ["worker_number=%s", "identity_status='confirmed'"]
            params = [worker_number]
            if status in REVIEW_STATUSES:
                clauses.append('review_status=%s')
                params.append(status)
            if ppe:
                clauses.append('FIND_IN_SET(%s, LOWER(missing_ppe)) > 0')
                params.append(str(ppe).strip().lower())
            where = ' AND '.join(clauses)
            conn = self._connect()
            c = conn.cursor()
            c.execute(f'SELECT COUNT(*) FROM instances WHERE {where}', tuple(params))
            total = c.fetchone()[0]
            c.execute(f'''
                SELECT instance_id, first_detected, missing_ppe, review_status, worker_comment,
                    worker_proof_path, worker_proof_at, review_reason, reviewed_by, review_updated_at
                FROM instances WHERE {where} ORDER BY first_detected DESC LIMIT %s OFFSET %s
            ''', tuple(params + [per_page, (page - 1) * per_page]))
            rows = c.fetchall()
            c.close()
            conn.close()
            items = [{
                'instance_id': r[0], 'first_detected': self._format_datetime(r[1]),
                'missing_ppe': [v for v in (r[2] or '').split(',') if v], 'review_status': r[3],
                'worker_comment': r[4], 'has_proof': bool(r[5]), 'worker_proof_at': self._format_datetime(r[6]),
                'review_reason': r[7], 'reviewed_by': r[8], 'review_updated_at': self._format_datetime(r[9]),
            } for r in rows]
            return {'items': items, 'page': page, 'per_page': per_page, 'total': total, 'has_more': page * per_page < total}
        except Exception as e:
            print(f"Error getting worker violations: {e}")
            return {'items': [], 'page': 1, 'per_page': 20, 'total': 0, 'has_more': False}

    def update_worker_profile(self, worker_number, phone, email, profile_photo_path=None):
        try:
            conn = self._connect()
            c = conn.cursor()
            if email:
                c.execute(
                    'SELECT worker_number FROM workers WHERE LOWER(email)=LOWER(%s) AND worker_number<>%s',
                    (email, worker_number),
                )
                if c.fetchone():
                    c.close()
                    conn.close()
                    return False, 'Email is already in use', None
            query = 'UPDATE workers SET phone=%s, email=%s, updated_at=CURRENT_TIMESTAMP'
            params = [phone or None, email or None]
            if profile_photo_path is not None:
                query += ', profile_photo_path=%s'
                params.append(profile_photo_path)
            query += ' WHERE worker_number=%s'
            params.append(worker_number)
            c.execute(query, tuple(params))
            conn.commit()
            c.close()
            conn.close()
            return True, 'Profile updated', self.get_worker_for_login(worker_number)
        except Exception as e:
            print(f"Error updating worker profile: {e}")
            return False, str(e), None

    def update_worker_password(self, worker_number, password_hash):
        try:
            conn = self._connect()
            c = conn.cursor()
            c.execute(
                'UPDATE workers SET password_hash=%s, updated_at=CURRENT_TIMESTAMP WHERE worker_number=%s',
                (password_hash, worker_number),
            )
            conn.commit()
            c.close()
            conn.close()
            return True
        except Exception as e:
            print(f"Error updating worker password: {e}")
            return False

    def submit_worker_proof(self, worker_number, instance_id, comment, proof_path):
        try:
            conn = self._connect()
            c = conn.cursor()
            c.execute('''
                SELECT review_status FROM instances
                WHERE instance_id=%s AND worker_number=%s AND identity_status='confirmed'
            ''', (instance_id, worker_number))
            row = c.fetchone()
            if not row or row[0] != 'pending':
                c.close()
                conn.close()
                return False, 'This alert cannot accept a worker submission'
            c.execute('''
                UPDATE instances SET review_status='worker_submitted', worker_acknowledged_at=CURRENT_TIMESTAMP,
                    worker_comment=%s, worker_proof_path=%s, worker_proof_at=CURRENT_TIMESTAMP
                WHERE instance_id=%s
            ''', (comment, proof_path, instance_id))
            c.execute('''
                INSERT INTO violation_review_events (instance_id, previous_status, review_status, review_reason, reviewer_name)
                VALUES (%s, 'pending', 'worker_submitted', %s, %s)
            ''', (instance_id, comment, worker_number))
            conn.commit()
            c.close()
            conn.close()
            return True, 'Proof submitted for supervisor review'
        except Exception as e:
            print(f"Error submitting worker proof: {e}")
            return False, str(e)

    def save_worker(self, worker, password_hash=None):
        try:
            worker_number = str(worker.get('worker_number', '')).strip().upper()
            name = str(worker.get('name', '')).strip()
            if not worker_number or not name:
                return False, 'Worker number and name are required'

            conn = self._connect()
            c = conn.cursor()
            c.execute('''
                INSERT INTO workers (worker_number, name, team, password_hash, is_active)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    name = VALUES(name),
                    team = VALUES(team),
                    password_hash = COALESCE(%s, password_hash),
                    is_active = VALUES(is_active),
                    updated_at = CURRENT_TIMESTAMP
            ''', (
                worker_number,
                name,
                worker.get('team'),
                password_hash,
                1 if worker.get('is_active', True) else 0,
                password_hash,
            ))
            conn.commit()
            c.close()
            conn.close()
            return True, 'Worker saved'
        except Exception as e:
            print(f"Error saving worker: {e}")
            return False, str(e)

    def delete_worker(self, worker_number):
        try:
            conn = self._connect()
            c = conn.cursor()
            c.execute('DELETE FROM workers WHERE worker_number = %s', (worker_number,))
            conn.commit()
            c.close()
            conn.close()
            return True
        except Exception as e:
            print(f"Error deleting worker: {e}")
            return False

    def _worker_from_row(self, row):
        return {
            'id': row[0],
            'worker_number': row[1],
            'name': row[2],
            'team': row[3],
            'is_active': bool(row[4]),
            'created_at': self._format_datetime(row[5]),
            'updated_at': self._format_datetime(row[6]),
        }

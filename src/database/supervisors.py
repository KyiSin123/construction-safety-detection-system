"""Supervisor accounts, devices, and the mobile violation feed they review."""

from .base import REVIEW_STATUSES


class SupervisorMixin:
    """Supervisor account management and the mobile-app violation/notification workflow."""

    def seed_initial_admin(self, username, password_hash, display_name):
        """Create the configured bootstrap admin once without replacing its password."""
        if not username or not password_hash:
            return False
        try:
            conn = self._connect()
            c = conn.cursor()
            c.execute('''
                INSERT INTO supervisors (username, password_hash, display_name, role)
                VALUES (%s, %s, %s, 'admin')
                ON DUPLICATE KEY UPDATE username = VALUES(username)
            ''', (username.strip().lower(), password_hash, display_name or username))
            conn.commit()
            c.close()
            conn.close()
            return True
        except Exception as e:
            print(f"Error seeding supervisor admin: {e}")
            return False

    def get_supervisor_by_username(self, username):
        try:
            conn = self._connect()
            c = conn.cursor()
            c.execute('''
                SELECT id, username, password_hash, display_name, role, is_active
                FROM supervisors WHERE username = %s
            ''', (str(username or '').strip().lower(),))
            row = c.fetchone()
            c.close()
            conn.close()
            if not row:
                return None
            return {
                'id': row[0], 'username': row[1], 'password_hash': row[2],
                'display_name': row[3], 'role': row[4], 'is_active': bool(row[5]),
            }
        except Exception as e:
            print(f"Error getting supervisor: {e}")
            return None

    def get_supervisor(self, supervisor_id):
        try:
            conn = self._connect()
            c = conn.cursor()
            c.execute('''
                SELECT id, username, display_name, role, is_active
                FROM supervisors WHERE id = %s
            ''', (supervisor_id,))
            row = c.fetchone()
            c.close()
            conn.close()
            return self._supervisor_from_row(row) if row else None
        except Exception as e:
            print(f"Error getting supervisor: {e}")
            return None

    def get_supervisors(self):
        try:
            conn = self._connect()
            c = conn.cursor()
            c.execute('''
                SELECT id, username, display_name, role, is_active
                FROM supervisors ORDER BY display_name, username
            ''')
            supervisors = [self._supervisor_from_row(row) for row in c.fetchall()]
            for supervisor in supervisors:
                c.execute(
                    'SELECT worker_number FROM supervisor_worker_assignments WHERE supervisor_id = %s',
                    (supervisor['id'],),
                )
                supervisor['worker_numbers'] = [row[0] for row in c.fetchall()]
                c.execute(
                    'SELECT team FROM supervisor_team_assignments WHERE supervisor_id = %s',
                    (supervisor['id'],),
                )
                supervisor['teams'] = [row[0] for row in c.fetchall()]
            c.close()
            conn.close()
            return supervisors
        except Exception as e:
            print(f"Error getting supervisors: {e}")
            return []

    def save_supervisor(self, payload, password_hash=None):
        username = str(payload.get('username') or '').strip().lower()
        display_name = str(payload.get('display_name') or '').strip()
        role = str(payload.get('role') or 'supervisor').strip().lower()
        if not username or not display_name or role not in {'admin', 'supervisor'}:
            return False, 'Username, display name, and a valid role are required', None
        try:
            conn = self._connect()
            c = conn.cursor()
            supervisor_id = payload.get('id')
            if supervisor_id:
                query = '''
                    UPDATE supervisors SET username = %s, display_name = %s, role = %s,
                        is_active = %s, updated_at = CURRENT_TIMESTAMP
                '''
                params = [username, display_name, role, 1 if payload.get('is_active', True) else 0]
                if password_hash:
                    query += ', password_hash = %s'
                    params.append(password_hash)
                query += ' WHERE id = %s'
                params.append(supervisor_id)
                c.execute(query, tuple(params))
            else:
                if not password_hash:
                    c.close()
                    conn.close()
                    return False, 'Password is required for a new supervisor', None
                c.execute('''
                    INSERT INTO supervisors (username, password_hash, display_name, role, is_active)
                    VALUES (%s, %s, %s, %s, %s)
                ''', (username, password_hash, display_name, role, 1 if payload.get('is_active', True) else 0))
                supervisor_id = c.lastrowid
            conn.commit()
            c.close()
            conn.close()
            return True, 'Supervisor saved', supervisor_id
        except Exception as e:
            print(f"Error saving supervisor: {e}")
            return False, str(e), None

    def set_supervisor_assignments(self, supervisor_id, worker_numbers=None, teams=None):
        worker_numbers = sorted({str(value).strip().upper() for value in (worker_numbers or []) if str(value).strip()})
        teams = sorted({str(value).strip() for value in (teams or []) if str(value).strip()})
        try:
            conn = self._connect()
            c = conn.cursor()
            c.execute('DELETE FROM supervisor_worker_assignments WHERE supervisor_id = %s', (supervisor_id,))
            c.execute('DELETE FROM supervisor_team_assignments WHERE supervisor_id = %s', (supervisor_id,))
            if worker_numbers:
                c.executemany(
                    'INSERT INTO supervisor_worker_assignments (supervisor_id, worker_number) VALUES (%s, %s)',
                    [(supervisor_id, value) for value in worker_numbers],
                )
            if teams:
                c.executemany(
                    'INSERT INTO supervisor_team_assignments (supervisor_id, team) VALUES (%s, %s)',
                    [(supervisor_id, value) for value in teams],
                )
            conn.commit()
            c.close()
            conn.close()
            return True, 'Assignments saved'
        except Exception as e:
            print(f"Error saving assignments: {e}")
            return False, str(e)

    def register_supervisor_device(self, supervisor_id, expo_push_token, platform=None):
        try:
            conn = self._connect()
            c = conn.cursor()
            c.execute('''
                INSERT INTO supervisor_devices (supervisor_id, expo_push_token, platform, is_active)
                VALUES (%s, %s, %s, 1)
                ON DUPLICATE KEY UPDATE supervisor_id = VALUES(supervisor_id), platform = VALUES(platform),
                    is_active = 1, last_seen_at = CURRENT_TIMESTAMP
            ''', (supervisor_id, expo_push_token, platform))
            conn.commit()
            c.close()
            conn.close()
            return True, 'Device registered'
        except Exception as e:
            print(f"Error registering device: {e}")
            return False, str(e)

    def deactivate_supervisor_device(self, supervisor_id, expo_push_token=None):
        try:
            conn = self._connect()
            c = conn.cursor()
            query = 'UPDATE supervisor_devices SET is_active = 0 WHERE supervisor_id = %s'
            params = [supervisor_id]
            if expo_push_token:
                query += ' AND expo_push_token = %s'
                params.append(expo_push_token)
            c.execute(query, tuple(params))
            conn.commit()
            c.close()
            conn.close()
            return True
        except Exception as e:
            print(f"Error deactivating device: {e}")
            return False

    def get_active_supervisor_devices(self, supervisor_id):
        try:
            conn = self._connect()
            c = conn.cursor()
            c.execute('''
                SELECT expo_push_token FROM supervisor_devices
                WHERE supervisor_id = %s AND is_active = 1
            ''', (supervisor_id,))
            tokens = [row[0] for row in c.fetchall()]
            c.close()
            conn.close()
            return tokens
        except Exception as e:
            print(f"Error getting supervisor devices: {e}")
            return []

    def assign_worker_to_violation(self, supervisor, instance_id, worker_number):
        """Atomically assign the first confirmed worker and create one logical push record."""
        worker_number = str(worker_number or '').strip().upper()
        conn = None
        try:
            conn = self._connect()
            c = conn.cursor()
            c.execute('''
                SELECT 1 FROM violation_notifications
                WHERE supervisor_id = %s AND instance_id = %s
            ''', (supervisor['id'], instance_id))
            if not c.fetchone():
                conn.rollback()
                c.close()
                conn.close()
                return False, 'This violation is not assigned to you', None
            c.execute('''
                SELECT worker_number, identity_status, review_status FROM instances
                WHERE instance_id = %s FOR UPDATE
            ''', (instance_id,))
            instance = c.fetchone()
            if not instance:
                conn.rollback()
                c.close()
                conn.close()
                return False, 'Violation not found', None
            if instance[2] != 'pending':
                conn.rollback()
                c.close()
                conn.close()
                return False, 'Only pending violations can be assigned', None
            if instance[0] or instance[1] == 'confirmed':
                conn.rollback()
                c.close()
                conn.close()
                return False, 'This violation has already been assigned', None
            c.execute('''
                SELECT worker_number, name, team FROM workers
                WHERE worker_number = %s AND is_active = 1
            ''', (worker_number,))
            worker = c.fetchone()
            if not worker:
                conn.rollback()
                c.close()
                conn.close()
                return False, 'Choose an active worker', None
            c.execute('''
                UPDATE instances SET worker_number = %s, worker_name = %s, worker_team = %s,
                    identity_status = 'confirmed', identity_source = 'supervisor_manual',
                    identity_confidence = 1, assigned_by_supervisor_id = %s,
                    assigned_by_name = %s, assigned_at = CURRENT_TIMESTAMP,
                    last_updated = CURRENT_TIMESTAMP
                WHERE instance_id = %s
            ''', (worker[0], worker[1], worker[2], supervisor['id'], supervisor['display_name'], instance_id))
            c.execute('''
                INSERT INTO violation_review_events
                    (instance_id, previous_status, review_status, review_reason,
                     supervisor_id, reviewer_name)
                VALUES (%s, 'pending', 'pending', %s, %s, %s)
            ''', (
                instance_id, f'Manually assigned to {worker[1]} ({worker[0]})',
                supervisor['id'], supervisor['display_name'],
            ))
            c.execute('''
                INSERT INTO worker_violation_notifications (instance_id, worker_number)
                VALUES (%s, %s)
            ''', (instance_id, worker[0]))
            notification_id = c.lastrowid
            c.execute('''
                SELECT expo_push_token FROM worker_devices
                WHERE worker_number = %s AND is_active = 1
            ''', (worker[0],))
            tokens = [row[0] for row in c.fetchall()]
            conn.commit()
            c.close()
            conn.close()
            return True, 'Worker assigned', {
                'notification_id': notification_id, 'worker_number': worker[0],
                'worker_name': worker[1], 'worker_team': worker[2], 'tokens': tokens,
            }
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                    conn.close()
                except Exception:
                    pass
            print(f"Error assigning worker: {e}")
            return False, str(e), None

    def update_worker_notification_status(self, notification_id, status, error=None):
        try:
            conn = self._connect()
            c = conn.cursor()
            c.execute('''
                UPDATE worker_violation_notifications
                SET delivery_status = %s, delivery_error = %s, notified_at = CURRENT_TIMESTAMP
                WHERE id = %s
            ''', (status, error, notification_id))
            conn.commit()
            c.close()
            conn.close()
        except Exception as e:
            print(f"Error updating worker notification: {e}")

    def create_supervisor_notifications(self, instance_id, identity=None):
        """Create recipient records, falling back to all active supervisors for unknown workers."""
        identity = identity or {}
        worker_number = str(identity.get('worker_number') or '').strip().upper()
        team = str(identity.get('team') or '').strip()
        identity_status = str(identity.get('identity_status') or 'unknown').strip().lower()
        unknown_identity = not worker_number or identity_status != 'confirmed'
        try:
            conn = self._connect()
            c = conn.cursor()
            if unknown_identity:
                c.execute('SELECT id FROM supervisors WHERE is_active = 1')
            else:
                clauses, params = [], []
                if worker_number:
                    clauses.append('swa.worker_number = %s')
                    params.append(worker_number)
                if team:
                    clauses.append('sta.team = %s')
                    params.append(team)
                c.execute(f'''
                    SELECT DISTINCT s.id
                    FROM supervisors s
                    LEFT JOIN supervisor_worker_assignments swa ON swa.supervisor_id = s.id
                    LEFT JOIN supervisor_team_assignments sta ON sta.supervisor_id = s.id
                    WHERE s.is_active = 1 AND ({' OR '.join(clauses)})
                ''', tuple(params))
            recipient_ids = [row[0] for row in c.fetchall()]
            if not recipient_ids:
                c.close()
                conn.close()
                return []
            placeholders = ','.join(['%s'] * len(recipient_ids))
            c.execute(
                f'SELECT supervisor_id FROM violation_notifications WHERE instance_id = %s AND supervisor_id IN ({placeholders})',
                (instance_id, *recipient_ids),
            )
            existing = {row[0] for row in c.fetchall()}
            created_ids = [value for value in recipient_ids if value not in existing]
            if created_ids:
                c.executemany(
                    'INSERT INTO violation_notifications (instance_id, supervisor_id) VALUES (%s, %s)',
                    [(instance_id, value) for value in created_ids],
                )
            if not created_ids:
                conn.commit()
                c.close()
                conn.close()
                return []
            placeholders = ','.join(['%s'] * len(created_ids))
            c.execute(f'''
                SELECT n.id, n.supervisor_id, s.display_name, d.expo_push_token
                FROM violation_notifications n
                JOIN supervisors s ON s.id = n.supervisor_id
                LEFT JOIN supervisor_devices d ON d.supervisor_id = s.id AND d.is_active = 1
                WHERE n.instance_id = %s AND n.supervisor_id IN ({placeholders})
            ''', (instance_id, *created_ids))
            rows = [
                {'notification_id': row[0], 'supervisor_id': row[1], 'display_name': row[2], 'expo_push_token': row[3]}
                for row in c.fetchall()
            ]
            conn.commit()
            c.close()
            conn.close()
            return rows
        except Exception as e:
            print(f"Error creating supervisor notifications: {e}")
            return []

    def update_supervisor_notification_status(self, notification_id, status, error=None):
        try:
            conn = self._connect()
            c = conn.cursor()
            c.execute('''
                UPDATE violation_notifications SET delivery_status = %s, delivery_error = %s,
                    notified_at = CURRENT_TIMESTAMP WHERE id = %s
            ''', (status, error, notification_id))
            conn.commit()
            c.close()
            conn.close()
        except Exception as e:
            print(f"Error updating supervisor notification: {e}")

    def ensure_unknown_violation_access(self, supervisor_id):
        """Make prior unknown-worker records visible without treating them as a new push alert."""
        try:
            conn = self._connect()
            c = conn.cursor()
            c.execute('''
                INSERT IGNORE INTO violation_notifications (instance_id, supervisor_id, delivery_status)
                SELECT i.instance_id, %s, 'historical'
                FROM instances i
                WHERE i.is_compliant = 0
                  AND (i.worker_number IS NULL OR i.worker_number = ''
                       OR i.identity_status IS NULL OR i.identity_status != 'confirmed')
            ''', (supervisor_id,))
            conn.commit()
            c.close()
            conn.close()
        except Exception as e:
            print(f"Error backfilling unknown violations: {e}")

    def get_mobile_violations(self, supervisor_id, status='pending'):
        if status not in REVIEW_STATUSES:
            status = 'pending'
        try:
            self.ensure_unknown_violation_access(supervisor_id)
            conn = self._connect()
            c = conn.cursor()
            c.execute('''
                SELECT i.instance_id, i.first_detected, i.last_updated, i.missing_ppe, i.detected_ppe,
                       i.worker_number, i.worker_name, i.worker_team, i.identity_status,
                       i.review_status, i.review_reason, i.reviewed_by, i.review_updated_at,
                       n.delivery_status, n.notified_at,
                       (SELECT COUNT(*) FROM snapshots s WHERE s.instance_id = i.instance_id),
                       CASE
                           WHEN i.worker_number IS NULL OR i.worker_number = ''
                                OR i.identity_status IS NULL OR i.identity_status != 'confirmed' THEN 1
                           WHEN FIND_IN_SET('helmet', LOWER(i.missing_ppe)) > 0 THEN 2
                           ELSE 3
                       END AS alert_priority,
                       n.is_read, n.read_at, i.worker_proof_at
                FROM violation_notifications n
                JOIN instances i ON i.instance_id = n.instance_id
                WHERE n.supervisor_id = %s AND i.review_status = %s
                ORDER BY alert_priority ASC, i.first_detected DESC
            ''', (supervisor_id, status))
            rows = c.fetchall()
            c.close()
            conn.close()
            return [self._mobile_violation_from_row(row) for row in rows]
        except Exception as e:
            print(f"Error getting mobile violations: {e}")
            return []

    def get_mobile_violation_counts(self, supervisor_id):
        try:
            self.ensure_unknown_violation_access(supervisor_id)
            conn=self._connect(); c=conn.cursor()
            c.execute("""SELECT i.review_status,COUNT(DISTINCT i.instance_id)
                FROM violation_notifications n JOIN instances i ON i.instance_id=n.instance_id
                WHERE n.supervisor_id=%s AND i.review_status IN ('pending','worker_submitted','resolved')
                GROUP BY i.review_status""",(supervisor_id,))
            counts={'pending':0,'worker_submitted':0,'resolved':0}
            for status,count in c.fetchall():
                if status in counts: counts[status]=count
            c.close(); conn.close(); return counts
        except Exception as e:
            print(f"Error getting mobile counts: {e}")
            return {'pending':0,'worker_submitted':0,'resolved':0}

    def get_mobile_violation_detail(self, supervisor_id, instance_id):
        try:
            conn = self._connect()
            c = conn.cursor()
            c.execute('''
                SELECT i.instance_id, i.first_detected, i.last_updated, i.missing_ppe, i.detected_ppe,
                       i.worker_number, i.worker_name, i.worker_team, i.identity_status,
                       i.review_status, i.review_reason, i.reviewed_by, i.review_updated_at,
                       n.delivery_status, n.notified_at,
                       (SELECT COUNT(*) FROM snapshots s WHERE s.instance_id = i.instance_id),
                       CASE
                           WHEN i.worker_number IS NULL OR i.worker_number = ''
                                OR i.identity_status IS NULL OR i.identity_status != 'confirmed' THEN 1
                           WHEN FIND_IN_SET('helmet', LOWER(i.missing_ppe)) > 0 THEN 2
                           ELSE 3
                       END AS alert_priority,
                       n.is_read, n.read_at
                FROM violation_notifications n JOIN instances i ON i.instance_id = n.instance_id
                WHERE n.supervisor_id = %s AND i.instance_id = %s
            ''', (supervisor_id, instance_id))
            row = c.fetchone()
            if not row:
                c.close()
                conn.close()
                return None
            result = self._mobile_violation_from_row(row)
            c.execute('''
                SELECT assigned_by_supervisor_id, assigned_by_name, assigned_at
                FROM instances WHERE instance_id = %s
            ''', (instance_id,))
            assignment = c.fetchone()
            result['assignment'] = {
                'supervisor_id': assignment[0],
                'supervisor_name': assignment[1],
                'assigned_at': self._format_datetime(assignment[2]),
            } if assignment and assignment[2] else None
            c.execute('''
                SELECT delivery_status, delivery_error, notified_at
                FROM worker_violation_notifications WHERE instance_id = %s
            ''', (instance_id,))
            delivery = c.fetchone()
            result['worker_delivery'] = {
                'status': delivery[0], 'error': delivery[1],
                'notified_at': self._format_datetime(delivery[2]),
            } if delivery else None
            c.execute('SELECT worker_comment,worker_proof_at FROM instances WHERE instance_id=%s',(instance_id,))
            proof=c.fetchone()
            result['worker_comment']=proof[0] if proof else None
            result['worker_proof_at']=self._format_datetime(proof[1]) if proof else None
            c.execute(
                'SELECT id, timestamp FROM snapshots WHERE instance_id = %s ORDER BY timestamp ASC',
                (instance_id,),
            )
            result['snapshots'] = [{'id': value[0], 'timestamp': self._format_datetime(value[1])} for value in c.fetchall()]
            c.execute('''
                SELECT previous_status, review_status, review_reason, reviewer_name, created_at
                FROM violation_review_events WHERE instance_id = %s ORDER BY created_at DESC
            ''', (instance_id,))
            result['review_events'] = [
                {'previous_status': value[0], 'review_status': value[1], 'review_reason': value[2],
                 'reviewed_by': value[3], 'created_at': self._format_datetime(value[4])}
                for value in c.fetchall()
            ]
            c.close()
            conn.close()
            return result
        except Exception as e:
            print(f"Error getting mobile violation: {e}")
            return None

    def get_mobile_snapshot_path(self, supervisor_id, snapshot_id):
        try:
            conn = self._connect()
            c = conn.cursor()
            c.execute('''
                SELECT s.snapshot_path FROM snapshots s
                JOIN violation_notifications n ON n.instance_id = s.instance_id
                WHERE s.id = %s AND n.supervisor_id = %s
            ''', (snapshot_id, supervisor_id))
            row = c.fetchone()
            c.close()
            conn.close()
            return row[0] if row else None
        except Exception as e:
            print(f"Error getting mobile snapshot: {e}")
            return None

    def get_worker_proof_path(self, supervisor_id, instance_id):
        try:
            conn = self._connect()
            c = conn.cursor()
            c.execute('''
                SELECT i.worker_proof_path FROM instances i
                JOIN violation_notifications n ON n.instance_id = i.instance_id
                WHERE n.supervisor_id = %s AND i.instance_id = %s
            ''', (supervisor_id, instance_id))
            row = c.fetchone()
            c.close()
            conn.close()
            return row[0] if row else None
        except Exception as e:
            print(f"Error getting worker proof: {e}")
            return None

    def get_mobile_unread_notification_count(self, supervisor_id):
        try:
            conn = self._connect()
            c = conn.cursor()
            c.execute('''
                SELECT COUNT(*) FROM violation_notifications
                WHERE supervisor_id = %s AND is_read = 0
            ''', (supervisor_id,))
            count = c.fetchone()[0]
            c.close()
            conn.close()
            return count
        except Exception as e:
            print(f"Error counting unread notifications: {e}")
            return 0

    def mark_mobile_notification_read(self, supervisor_id, instance_id=None):
        try:
            conn = self._connect()
            c = conn.cursor()
            query = '''
                UPDATE violation_notifications SET is_read = 1, read_at = COALESCE(read_at, CURRENT_TIMESTAMP)
                WHERE supervisor_id = %s AND is_read = 0
            '''
            params = [supervisor_id]
            if instance_id:
                query += ' AND instance_id = %s'
                params.append(instance_id)
            c.execute(query, tuple(params))
            updated = c.rowcount
            conn.commit()
            c.close()
            conn.close()
            return True, updated
        except Exception as e:
            print(f"Error marking notifications read: {e}")
            return False, 0

    def update_mobile_review(self, supervisor, instance_id, review_status, review_reason=None):
        supervisor_id = supervisor.get('id')
        try:
            conn = self._connect()
            c = conn.cursor()
            c.execute(
                '''SELECT i.worker_number FROM violation_notifications n JOIN instances i ON i.instance_id=n.instance_id
                   WHERE n.supervisor_id=%s AND n.instance_id=%s''',
                (supervisor_id, instance_id),
            )
            violation = c.fetchone()
            c.close()
            conn.close()
            if not violation:
                return False, 'This violation is not assigned to you', None
            ok, message = self.update_instance_review(instance_id, review_status, review_reason, supervisor.get('display_name'))
            if ok:
                conn = self._connect()
                c = conn.cursor()
                c.execute('''
                    UPDATE violation_review_events SET supervisor_id = %s
                    WHERE instance_id = %s ORDER BY id DESC LIMIT 1
                ''', (supervisor_id, instance_id))
                action={'review_status':str(review_status).strip().lower()}
                if action['review_status']=='pending':
                    c.execute('''SELECT d.expo_push_token FROM instances i JOIN worker_devices d ON d.worker_number=i.worker_number
                        WHERE i.instance_id=%s AND d.is_active=1''',(instance_id,))
                    action['worker_tokens']=[row[0] for row in c.fetchall()]
                conn.commit()
                c.close()
                conn.close()
                return True,message,action
            return False,message,None
        except Exception as e:
            print(f"Error updating mobile review: {e}")
            return False, str(e), None

    def _supervisor_from_row(self, row):
        return {
            'id': row[0], 'username': row[1], 'display_name': row[2],
            'role': row[3], 'is_active': bool(row[4]),
        }

    def _mobile_violation_from_row(self, row):
        return {
            'instance_id': row[0], 'first_detected': self._format_datetime(row[1]),
            'last_updated': self._format_datetime(row[2]),
            'missing_ppe': (row[3] or '').split(',') if row[3] else [],
            'detected_ppe': (row[4] or '').split(',') if row[4] else [],
            'worker_number': row[5], 'worker_name': row[6], 'worker_team': row[7],
            'identity_status': row[8] or 'unknown', 'review_status': row[9] or 'pending',
            'review_reason': row[10], 'reviewed_by': row[11],
            'review_updated_at': self._format_datetime(row[12]), 'delivery_status': row[13],
            'notified_at': self._format_datetime(row[14]), 'snapshot_count': row[15],
            'alert_priority': row[16], 'is_read': bool(row[17]),
            'read_at': self._format_datetime(row[18]),
            'worker_proof_at': self._format_datetime(row[19]) if len(row)>19 else None,
        }

    def supervisor_attendance_requests(self, supervisor_id, status='pending'):
        try:
            conn = self._connect()
            c = conn.cursor()
            params = [supervisor_id, supervisor_id]
            status_clause = ''
            if status in {'pending', 'approved', 'rejected'}:
                status_clause = ' AND ar.status=%s'
                params.append(status)
            c.execute(f'''
                SELECT ar.id, ar.action, ar.requested_at, ar.reason, ar.status, ar.reviewer_name,
                    ar.decision_reason, ar.decided_at, ar.created_at, w.worker_number, w.name, w.team
                FROM attendance_requests ar JOIN workers w ON w.worker_number=ar.worker_number
                WHERE (EXISTS(SELECT 1 FROM supervisor_worker_assignments wa WHERE wa.supervisor_id=%s AND wa.worker_number=w.worker_number)
                  OR EXISTS(SELECT 1 FROM supervisor_team_assignments ta WHERE ta.supervisor_id=%s AND ta.team=w.team))
                {status_clause} ORDER BY ar.created_at DESC
            ''', tuple(params))
            rows = c.fetchall()
            c.close()
            conn.close()
            return [
                {**self._attendance_request_from_row(r[:9]), 'worker_number': r[9], 'worker_name': r[10], 'worker_team': r[11]}
                for r in rows
            ]
        except Exception as e:
            print(f"Error listing supervisor attendance requests: {e}")
            return []

    def decide_attendance_request(self, supervisor, request_id, decision, decision_reason=None):
        if decision not in {'approved', 'rejected'}:
            return False, 'Choose approve or reject'
        decision_reason = str(decision_reason or '').strip()
        if decision == 'rejected' and not decision_reason:
            return False, 'A rejection reason is required'
        conn = None
        try:
            conn = self._connect()
            c = conn.cursor()
            conn.start_transaction()
            c.execute('''
                SELECT ar.worker_number, ar.action, ar.requested_at, ar.reason, ar.status, w.team
                FROM attendance_requests ar JOIN workers w ON w.worker_number=ar.worker_number
                WHERE ar.id=%s FOR UPDATE
            ''', (request_id,))
            row = c.fetchone()
            if not row or row[4] != 'pending':
                conn.rollback()
                c.close()
                conn.close()
                return False, 'Request is no longer pending'
            c.execute('''
                SELECT 1 WHERE EXISTS(SELECT 1 FROM supervisor_worker_assignments WHERE supervisor_id=%s AND worker_number=%s)
                OR EXISTS(SELECT 1 FROM supervisor_team_assignments WHERE supervisor_id=%s AND team=%s)
            ''', (supervisor['id'], row[0], supervisor['id'], row[5]))
            if not c.fetchone():
                conn.rollback()
                c.close()
                conn.close()
                return False, 'This worker is not assigned to you'
            attendance_id = None
            if decision == 'approved':
                requested_at = row[2]
                attendance_date = requested_at.date()
                c.execute(
                    'SELECT id, check_in_at, check_out_at FROM attendance_records WHERE worker_number=%s AND attendance_date=%s FOR UPDATE',
                    (row[0], attendance_date),
                )
                attendance = c.fetchone()
                if row[1] == 'check_in':
                    if attendance:
                        conn.rollback()
                        c.close()
                        conn.close()
                        return False, 'Attendance already has a check-in for this date'
                    c.execute('''
                        INSERT INTO attendance_records (worker_number, attendance_date, check_in_at, recorded_by, check_in_reason)
                        VALUES (%s, %s, %s, %s, %s)
                    ''', (row[0], attendance_date, requested_at, supervisor['display_name'], row[3]))
                    attendance_id = c.lastrowid
                else:
                    if not attendance:
                        conn.rollback()
                        c.close()
                        conn.close()
                        return False, 'A check-in must be recorded before approving check-out'
                    if attendance[2]:
                        conn.rollback()
                        c.close()
                        conn.close()
                        return False, 'Attendance already has a check-out for this date'
                    if requested_at < attendance[1]:
                        conn.rollback()
                        c.close()
                        conn.close()
                        return False, 'Requested check-out is before check-in'
                    attendance_id = attendance[0]
                    c.execute('''
                        UPDATE attendance_records SET check_out_at=%s, recorded_by=%s, check_out_reason=%s WHERE id=%s
                    ''', (requested_at, supervisor['display_name'], row[3], attendance_id))
            c.execute('''
                UPDATE attendance_requests SET status=%s, reviewed_by=%s, reviewer_name=%s,
                    decision_reason=%s, decided_at=CURRENT_TIMESTAMP, attendance_record_id=%s WHERE id=%s
            ''', (decision, supervisor['id'], supervisor['display_name'], decision_reason or None, attendance_id, request_id))
            conn.commit()
            c.close()
            conn.close()
            return True, 'Attendance request ' + decision
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                    conn.close()
                except Exception:
                    pass
            print(f"Error deciding attendance request: {e}")
            return False, str(e)

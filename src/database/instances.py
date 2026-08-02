"""Violation instance lifecycle: detection storage, review status, and dashboard analytics."""

import os
from datetime import timedelta

from .base import REVIEW_STATUSES, BLOCKING_REVIEW_STATUSES


class InstanceMixin:
    """Violation instance CRUD, review workflow, and analytics aggregation."""

    def find_blocking_violation(self, missing_ppe, identity=None, detection_batch_id=None):
        """Block a duplicate open violation only within the current calendar date."""
        try:
            normalized_missing_ppe = self._normalize_missing_ppe(missing_ppe)
            if not normalized_missing_ppe:
                return None

            identity = identity or {}
            worker_number = identity.get('worker_number')
            worker_number = str(worker_number).strip().upper() if worker_number else None
            blocking_statuses = tuple(sorted(BLOCKING_REVIEW_STATUSES))

            conn = self._connect()
            c = conn.cursor()
            if worker_number:
                c.execute('''
                    SELECT instance_id
                    FROM instances
                    WHERE is_compliant = 0
                      AND review_status = 'pending'
                      AND DATE(first_detected) = CURDATE()
                      AND worker_number = %s
                    ORDER BY first_detected ASC
                    LIMIT 1
                ''', (worker_number,))
                row = c.fetchone()
                c.close()
                conn.close()
                return row[0] if row else None
            else:
                c.execute('''
                    SELECT instance_id, missing_ppe
                    FROM instances
                    WHERE is_compliant = 0
                      AND review_status IN (%s, %s)
                      AND DATE(first_detected) = CURDATE()
                      AND (worker_number IS NULL OR worker_number = '')
                      AND (%s IS NULL OR detection_batch_id IS NULL OR detection_batch_id != %s)
                    ORDER BY first_detected ASC
                ''', (*blocking_statuses, detection_batch_id, detection_batch_id))

            rows = c.fetchall()
            c.close()
            conn.close()

            for instance_id, stored_missing_ppe in rows:
                if self._normalize_missing_ppe(stored_missing_ppe) == normalized_missing_ppe:
                    return instance_id
            return None
        except Exception as e:
            print(f"Error checking blocking violation: {e}")
            return None

    def log_instance_snapshot(
        self, instance_id, missing_ppe, detected_ppe, snapshot_path, identity=None,
        detection_batch_id=None,
    ):
        """Log a snapshot for an instance."""
        try:
            if not instance_id or not snapshot_path:
                return False
            snapshot_data = None
            try:
                if os.path.isfile(snapshot_path) and os.path.getsize(snapshot_path) <= 5 * 1024 * 1024:
                    with open(snapshot_path, 'rb') as snapshot_file:
                        snapshot_data = snapshot_file.read()
            except OSError as error:
                print(f"Could not read snapshot data for database storage: {error}")
            identity = identity or {}
            missing_ppe_text = self._missing_ppe_text(missing_ppe)
            detected_ppe_text = self._missing_ppe_text(detected_ppe)

            conn = self._connect()
            c = conn.cursor()

            c.execute('SELECT id FROM instances WHERE instance_id = %s', (instance_id,))
            if not c.fetchone():
                c.execute('''
                    INSERT INTO instances (
                        instance_id, is_compliant, missing_ppe, detected_ppe,
                        detection_batch_id,
                        worker_number, worker_name, worker_team, identity_confidence,
                        identity_status, identity_source, identity_raw_response
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ''', (
                    instance_id, False, missing_ppe_text, detected_ppe_text,
                    detection_batch_id,
                    identity.get('worker_number'), identity.get('worker_name'), identity.get('team'),
                    identity.get('identity_confidence', 0), identity.get('identity_status', 'unknown'),
                    identity.get('identity_source'), identity.get('raw_response')
                ))
                print(f"Created new instance record: {instance_id}")
            else:
                c.execute('''
                    UPDATE instances
                    SET last_updated = CURRENT_TIMESTAMP,
                        missing_ppe = %s,
                        detected_ppe = %s,
                        detection_batch_id = COALESCE(%s, detection_batch_id),
                        worker_number = COALESCE(%s, worker_number),
                        worker_name = COALESCE(%s, worker_name),
                        worker_team = COALESCE(%s, worker_team),
                        identity_confidence = CASE WHEN %s > identity_confidence THEN %s ELSE identity_confidence END,
                        identity_status = CASE WHEN %s IN ('confirmed', 'unregistered', 'low_confidence', 'pending_review') THEN %s ELSE identity_status END,
                        identity_source = COALESCE(%s, identity_source),
                        identity_raw_response = COALESCE(%s, identity_raw_response)
                    WHERE instance_id = %s
                ''', (
                    missing_ppe_text, detected_ppe_text,
                    detection_batch_id,
                    identity.get('worker_number'), identity.get('worker_name'), identity.get('team'),
                    identity.get('identity_confidence', 0), identity.get('identity_confidence', 0),
                    identity.get('identity_status'), identity.get('identity_status'),
                    identity.get('identity_source'), identity.get('raw_response'),
                    instance_id
                ))

            c.execute('''
                INSERT INTO snapshots (instance_id, snapshot_path, snapshot_data, mime_type)
                VALUES (%s, %s, %s, 'image/jpeg')
            ''', (instance_id, snapshot_path, snapshot_data))

            conn.commit()
            c.close()
            conn.close()
            print(f"Logged snapshot for {instance_id}: {snapshot_path}")
            return True
        except Exception as e:
            print(f"Error logging instance snapshot: {e}")
            return False

    def claim_unknown_alert_batch(self, detection_batch_id):
        """Atomically allow every unknown person in only the first detection batch of the day."""
        if not detection_batch_id:
            return False
        conn = None
        c = None
        try:
            conn = self._connect()
            c = conn.cursor()
            c.execute('''
                SELECT detection_batch_id, created_at
                FROM unknown_alert_daily_batches
                WHERE alert_date = CURDATE()
            ''')
            row = c.fetchone()
            if row:
                if row[0] == detection_batch_id:
                    return True
                c.execute('''
                    SELECT COUNT(*),
                           COALESCE(SUM(
                             (worker_number IS NULL OR worker_number = ''
                               OR identity_status IS NULL
                               OR identity_status != 'confirmed')
                             AND (review_status IS NULL OR review_status != 'resolved')
                           ), 0)
                    FROM instances
                    WHERE detection_batch_id = %s
                ''', (row[0],))
                instance_count, unknown_count = c.fetchone()
                c.execute(
                    'SELECT TIMESTAMPDIFF(SECOND, %s, CURRENT_TIMESTAMP)',
                    (row[1],),
                )
                reservation_age = c.fetchone()[0] or 0
                if unknown_count > 0 or (instance_count == 0 and reservation_age < 300):
                    return False
                # Recover a reservation left behind either when a process stopped
                # before persisting, or when every unknown person in the claimed
                # batch was subsequently identified or resolved by a supervisor.
                c.execute(
                    'DELETE FROM unknown_alert_daily_batches '
                    'WHERE alert_date=CURDATE() AND detection_batch_id=%s',
                    (row[0],),
                )
                conn.commit()

            # Respect unknown alerts created earlier today by Live Detection or
            # by a deployment version that predates batch IDs. A resolved case no
            # longer holds the day's slot even if the person was never identified.
            c.execute('''
                SELECT detection_batch_id
                FROM instances
                WHERE is_compliant = 0
                  AND DATE(first_detected) = CURDATE()
                  AND (
                    worker_number IS NULL OR worker_number = ''
                    OR identity_status IS NULL OR identity_status != 'confirmed'
                  )
                  AND (review_status IS NULL OR review_status != 'resolved')
                ORDER BY first_detected ASC
                LIMIT 1
            ''')
            prior = c.fetchone()
            if prior and prior[0] != detection_batch_id:
                return False

            # The primary key on alert_date is the concurrency lock. INSERT
            # IGNORE is supported by managed MySQL services that disable the
            # GET_LOCK advisory-lock function.
            c.execute('''
                INSERT IGNORE INTO unknown_alert_daily_batches
                    (alert_date, detection_batch_id)
                VALUES (CURDATE(), %s)
            ''', (detection_batch_id,))
            conn.commit()
            c.execute('''
                SELECT detection_batch_id
                FROM unknown_alert_daily_batches
                WHERE alert_date=CURDATE()
            ''')
            owner = c.fetchone()
            return bool(owner and owner[0] == detection_batch_id)
        except Exception as e:
            print(f"Error claiming unknown alert batch: {e}")
            return False
        finally:
            if c is not None:
                c.close()
            if conn is not None:
                conn.close()

    def release_unknown_alert_batch(self, detection_batch_id):
        """Release this batch only when it did not persist any violation."""
        if not detection_batch_id:
            return False
        try:
            conn = self._connect()
            c = conn.cursor()
            c.execute('''
                DELETE b FROM unknown_alert_daily_batches b
                WHERE b.alert_date=CURDATE() AND b.detection_batch_id=%s
                  AND NOT EXISTS (
                    SELECT 1 FROM instances i
                    WHERE i.detection_batch_id=b.detection_batch_id
                  )
            ''', (detection_batch_id,))
            released = c.rowcount > 0
            conn.commit()
            c.close()
            conn.close()
            return released
        except Exception as e:
            print(f"Error releasing unknown alert batch: {e}")
            return False

    def get_statistics(self):
        """Get dashboard statistics from persisted violation instances."""
        try:
            conn = self._connect()
            c = conn.cursor()

            c.execute('SELECT COUNT(*) FROM instances WHERE is_compliant = 0')
            total_violations = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM instances WHERE is_compliant = 0 AND review_status = 'pending'")
            pending_violations = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM instances WHERE is_compliant = 0 AND review_status = 'resolved'")
            resolved_violations = c.fetchone()[0]

            c.close()
            conn.close()

            return {
                'total_violations': total_violations,
                'pending_violations': pending_violations,
                'resolved_violations': resolved_violations,
            }
        except Exception as e:
            print(f"Error getting statistics: {e}")
            return {
                'total_violations': 0,
                'pending_violations': 0,
                'resolved_violations': 0,
            }

    def get_detection_analysis(self, days=7):
        """Aggregate persisted violation instances for the admin dashboard."""
        days = days if days in {7, 30, 90} else 7
        try:
            conn = self._connect()
            c = conn.cursor()
            start_offset = days - 1
            date_filter = (
                f"first_detected >= DATE_SUB(CURDATE(), INTERVAL {start_offset} DAY) "
                "AND first_detected < DATE_ADD(CURDATE(), INTERVAL 1 DAY) "
                "AND is_compliant = 0"
            )

            c.execute('SELECT CURDATE()')
            end_date = c.fetchone()[0]

            c.execute(f'''
                SELECT DATE(first_detected), COUNT(*)
                FROM instances
                WHERE {date_filter}
                GROUP BY DATE(first_detected)
                ORDER BY DATE(first_detected)
            ''')
            daily_counts = {row[0]: row[1] for row in c.fetchall()}

            c.execute(f'''
                SELECT COALESCE(review_status, 'pending'), COUNT(*)
                FROM instances
                WHERE {date_filter}
                GROUP BY COALESCE(review_status, 'pending')
            ''')
            status_counts = {str(row[0]): row[1] for row in c.fetchall()}

            c.execute(f'''
                SELECT missing_ppe
                FROM instances
                WHERE {date_filter}
            ''')
            missing_ppe_counts = {}
            for row in c.fetchall():
                for item in self._normalize_missing_ppe(row[0]):
                    missing_ppe_counts[item] = missing_ppe_counts.get(item, 0) + 1

            c.execute(f'''
                SELECT HOUR(first_detected), COUNT(*)
                FROM instances
                WHERE {date_filter}
                GROUP BY HOUR(first_detected)
                ORDER BY HOUR(first_detected)
            ''')
            hourly_counts = {int(row[0]): row[1] for row in c.fetchall()}

            c.close()
            conn.close()

            start_date = end_date - timedelta(days=start_offset)
            daily = []
            for offset in range(days):
                current_date = start_date + timedelta(days=offset)
                daily.append({
                    'date': current_date.isoformat(),
                    'count': daily_counts.get(current_date, 0),
                })

            review_statuses = [
                {'label': status, 'count': status_counts.get(status, 0)}
                for status in ('pending', 'worker_submitted', 'resolved')
            ]
            known_statuses = {item['label'] for item in review_statuses}
            review_statuses.extend(
                {'label': status, 'count': count}
                for status, count in sorted(status_counts.items())
                if status not in known_statuses
            )

            return {
                'days': days,
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat(),
                'total_violations': sum(daily_counts.values()),
                'daily': daily,
                'hourly': [
                    {'hour': hour, 'count': hourly_counts.get(hour, 0)}
                    for hour in range(24)
                ],
                'missing_ppe': [
                    {'label': label, 'count': count}
                    for label, count in sorted(
                        missing_ppe_counts.items(),
                        key=lambda item: (-item[1], item[0]),
                    )
                ],
                'review_statuses': review_statuses,
            }
        except Exception as e:
            print(f"Error getting detection analysis: {e}")
            return None

    def get_all_instances(self, sort_by='first_detected', sort_order='desc', status=None):
        """Get all instances."""
        try:
            allowed_sort_columns = {'first_detected', 'last_updated', 'review_updated_at'}
            if sort_by not in allowed_sort_columns:
                sort_by = 'first_detected'
            sort_order = sort_order.lower()
            if sort_order not in {'asc', 'desc'}:
                sort_order = 'desc'
            if status not in REVIEW_STATUSES:
                status = None

            conn = self._connect()
            c = conn.cursor()

            query = '''
                SELECT i.id,i.instance_id,i.first_detected,i.last_updated,i.is_compliant,
                       i.missing_ppe,i.detected_ppe,i.worker_number,i.worker_name,i.worker_team,
                       i.identity_confidence,i.identity_status,i.identity_source,i.identity_raw_response,
                       i.notification_status,i.notification_error,i.review_status,i.review_reason,
                       i.reviewed_by,i.review_updated_at,COALESCE(s.snapshot_count,0) AS snapshot_count
                FROM instances i
                LEFT JOIN (
                    SELECT instance_id, COUNT(*) as snapshot_count
                    FROM snapshots
                    GROUP BY instance_id
                ) s ON i.instance_id = s.instance_id
                WHERE i.is_compliant = 0
            '''
            params = []
            if status:
                query += ' AND i.review_status = %s'
                params.append(status)

            query += f' ORDER BY i.{sort_by} {sort_order}'

            c.execute(query, tuple(params))
            rows = c.fetchall()
            c.close()
            conn.close()

            instances = []
            for row in rows:
                instances.append({
                    'id': row[0],
                    'instance_id': row[1],
                    'first_detected': self._format_datetime(row[2]),
                    'last_updated': self._format_datetime(row[3]),
                    'is_compliant': bool(row[4]),
                    'missing_ppe': row[5].split(',') if row[5] else [],
                    'detected_ppe': row[6].split(',') if row[6] else [],
                    'worker_number': row[7],
                    'worker_name': row[8],
                    'worker_team': row[9],
                    'identity_confidence': row[10] or 0,
                    'identity_status': row[11] or 'unknown',
                    'notification_status': row[14] or 'not_sent',
                    'notification_error': row[15],
                    'review_status': row[16] or 'pending',
                    'review_reason': row[17],
                    'reviewed_by': row[18],
                    'review_updated_at': self._format_datetime(row[19]),
                    'snapshot_count': row[20]
                })

            return instances
        except Exception as e:
            print(f"Error getting instances: {e}")
            return []

    def get_instance_snapshots(self, instance_id):
        """Get all snapshots for a specific instance."""
        try:
            conn = self._connect()
            c = conn.cursor()

            c.execute('''
                SELECT instance_id, first_detected, last_updated, missing_ppe, detected_ppe,
                       worker_number, worker_name, worker_team, identity_confidence,
                       identity_status, identity_source, identity_raw_response,
                       notification_status, notification_error, review_status,
                       review_reason, reviewed_by, review_updated_at
                FROM instances WHERE instance_id = %s
            ''', (instance_id,))
            instance_row = c.fetchone()

            if not instance_row:
                c.close()
                conn.close()
                return None

            c.execute('''
                SELECT id, snapshot_path, timestamp
                FROM snapshots
                WHERE instance_id = %s
                ORDER BY timestamp ASC
            ''', (instance_id,))
            snapshot_rows = c.fetchall()

            c.close()
            conn.close()

            return {
                'instance_id': instance_row[0],
                'first_detected': self._format_datetime(instance_row[1]),
                'last_updated': self._format_datetime(instance_row[2]),
                'missing_ppe': instance_row[3].split(',') if instance_row[3] else [],
                'detected_ppe': instance_row[4].split(',') if instance_row[4] else [],
                'worker_number': instance_row[5],
                'worker_name': instance_row[6],
                'worker_team': instance_row[7],
                'identity_confidence': instance_row[8] or 0,
                'identity_status': instance_row[9] or 'unknown',
                'identity_source': instance_row[10],
                'identity_raw_response': instance_row[11],
                'notification_status': instance_row[12] or 'not_sent',
                'notification_error': instance_row[13],
                'review_status': instance_row[14] or 'pending',
                'review_reason': instance_row[15],
                'reviewed_by': instance_row[16],
                'review_updated_at': self._format_datetime(instance_row[17]),
                'snapshots': [
                    {'id': row[0], 'path': row[1], 'timestamp': self._format_datetime(row[2])}
                    for row in snapshot_rows
                ]
            }
        except Exception as e:
            print(f"Error getting instance snapshots: {e}")
            return None

    def get_admin_snapshot_media(self, snapshot_id):
        """Return snapshot bytes/path for an authenticated administrator."""
        try:
            conn = self._connect()
            c = conn.cursor()
            c.execute('''
                SELECT snapshot_path, snapshot_data, mime_type
                FROM snapshots WHERE id=%s
            ''', (snapshot_id,))
            row = c.fetchone()
            c.close()
            conn.close()
            return {
                'path': row[0],
                'data': bytes(row[1]) if row[1] is not None else None,
                'mime_type': row[2] or 'image/jpeg',
            } if row else None
        except Exception as e:
            print(f"Error getting admin snapshot: {e}")
            return None

    def update_instance_review(self, instance_id, review_status, review_reason=None, reviewed_by=None):
        try:
            review_status = str(review_status or '').strip().lower()
            review_reason = str(review_reason or '').strip()
            reviewed_by = str(reviewed_by or '').strip() or None

            if review_status not in REVIEW_STATUSES:
                return False, 'Review status must be pending, worker_submitted, or resolved'

            conn = self._connect()
            c = conn.cursor()
            c.execute(
                'SELECT missing_ppe, review_status, worker_proof_path FROM instances WHERE instance_id = %s AND is_compliant = 0',
                (instance_id,)
            )
            row = c.fetchone()
            if not row:
                c.close()
                conn.close()
                return False, 'Instance not found'

            previous_status = row[1] or 'pending'
            if previous_status == 'resolved':
                c.close(); conn.close(); return False, 'Resolved violations are read-only'
            if review_status == 'worker_submitted':
                c.close(); conn.close(); return False, 'Only worker proof can set worker_submitted'
            if review_status == 'resolved' and previous_status == 'pending' and not review_reason:
                c.close(); conn.close(); return False, 'A reason is required when resolving directly'
            if review_status == 'resolved' and previous_status == 'worker_submitted' and not row[2]:
                c.close(); conn.close(); return False, 'Worker proof is required before approval'
            if review_status == 'pending' and previous_status == 'worker_submitted' and not review_reason:
                c.close(); conn.close(); return False, 'A reason is required when requesting new proof'
            if review_status == previous_status:
                c.close(); conn.close(); return False, 'Choose a valid review action'

            c.execute('''
                UPDATE instances
                SET review_status = %s,
                    review_reason = %s,
                    reviewed_by = %s,
                    review_updated_at = CURRENT_TIMESTAMP
                WHERE instance_id = %s
            ''', (review_status, review_reason or None, reviewed_by, instance_id))
            c.execute('''
                INSERT INTO violation_review_events (
                    instance_id, previous_status, review_status, review_reason, reviewer_name
                ) VALUES (%s, %s, %s, %s, %s)
            ''', (instance_id, previous_status, review_status, review_reason or None, reviewed_by))
            conn.commit()
            c.close()
            conn.close()
            return True, 'Review updated'
        except Exception as e:
            print(f"Error updating instance review: {e}")
            return False, str(e)

    def delete_instance(self, instance_id):
        """Delete an instance and all its snapshots."""
        try:
            conn = self._connect()
            c = conn.cursor()

            c.execute('SELECT snapshot_path FROM snapshots WHERE instance_id = %s', (instance_id,))
            rows = c.fetchall()

            for row in rows:
                if row[0] and os.path.exists(row[0]):
                    os.remove(row[0])

            c.execute('DELETE FROM snapshots WHERE instance_id = %s', (instance_id,))
            c.execute('DELETE FROM instances WHERE instance_id = %s', (instance_id,))

            conn.commit()
            c.close()
            conn.close()

            return True
        except Exception as e:
            print(f"Error deleting instance: {e}")
            return False

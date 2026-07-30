"""Violation instance lifecycle: detection storage, review status, and dashboard analytics."""

import os
from datetime import timedelta

from .base import REVIEW_STATUSES, BLOCKING_REVIEW_STATUSES


class InstanceMixin:
    """Violation instance CRUD, review workflow, and analytics aggregation."""

    def find_blocking_violation(self, missing_ppe, identity=None):
        """Return an unresolved matching violation id, if pending/ignored should block storage."""
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
                    SELECT instance_id, missing_ppe
                    FROM instances
                    WHERE is_compliant = 0
                      AND review_status IN (%s, %s)
                      AND worker_number = %s
                    ORDER BY first_detected ASC
                ''', (*blocking_statuses, worker_number))
            else:
                c.execute('''
                    SELECT instance_id, missing_ppe
                    FROM instances
                    WHERE is_compliant = 0
                      AND review_status IN (%s, %s)
                      AND (worker_number IS NULL OR worker_number = '')
                    ORDER BY first_detected ASC
                ''', blocking_statuses)

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

    def log_instance_snapshot(self, instance_id, missing_ppe, detected_ppe, snapshot_path, identity=None):
        """Log a snapshot for an instance."""
        try:
            if not instance_id or not snapshot_path:
                return False
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
                        worker_number, worker_name, worker_team, identity_confidence,
                        identity_status, identity_source, identity_raw_response
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ''', (
                    instance_id, False, missing_ppe_text, detected_ppe_text,
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
                    identity.get('worker_number'), identity.get('worker_name'), identity.get('team'),
                    identity.get('identity_confidence', 0), identity.get('identity_confidence', 0),
                    identity.get('identity_status'), identity.get('identity_status'),
                    identity.get('identity_source'), identity.get('raw_response'),
                    instance_id
                ))

            c.execute('''
                INSERT INTO snapshots (instance_id, snapshot_path)
                VALUES (%s, %s)
            ''', (instance_id, snapshot_path))

            conn.commit()
            c.close()
            conn.close()
            print(f"Logged snapshot for {instance_id}: {snapshot_path}")
            return True
        except Exception as e:
            print(f"Error logging instance snapshot: {e}")
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
                for status in ('pending', 'worker_submitted', 'resolved', 'ignored')
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
                SELECT i.*, COALESCE(s.snapshot_count, 0) as snapshot_count
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

            c.execute('SELECT * FROM instances WHERE instance_id = %s', (instance_id,))
            instance_row = c.fetchone()

            if not instance_row:
                c.close()
                conn.close()
                return None

            c.execute('''
                SELECT snapshot_path, timestamp
                FROM snapshots
                WHERE instance_id = %s
                ORDER BY timestamp ASC
            ''', (instance_id,))
            snapshot_rows = c.fetchall()

            c.close()
            conn.close()

            return {
                'instance_id': instance_row[1],
                'first_detected': self._format_datetime(instance_row[2]),
                'last_updated': self._format_datetime(instance_row[3]),
                'missing_ppe': instance_row[5].split(',') if instance_row[5] else [],
                'detected_ppe': instance_row[6].split(',') if instance_row[6] else [],
                'worker_number': instance_row[7],
                'worker_name': instance_row[8],
                'worker_team': instance_row[9],
                'identity_confidence': instance_row[10] or 0,
                'identity_status': instance_row[11] or 'unknown',
                'identity_source': instance_row[12],
                'identity_raw_response': instance_row[13],
                'notification_status': instance_row[14] or 'not_sent',
                'notification_error': instance_row[15],
                'review_status': instance_row[16] or 'pending',
                'review_reason': instance_row[17],
                'reviewed_by': instance_row[18],
                'review_updated_at': self._format_datetime(instance_row[19]),
                'snapshots': [
                    {'path': row[0], 'timestamp': self._format_datetime(row[1])}
                    for row in snapshot_rows
                ]
            }
        except Exception as e:
            print(f"Error getting instance snapshots: {e}")
            return None

    def update_instance_review(self, instance_id, review_status, review_reason=None, reviewed_by=None):
        try:
            review_status = str(review_status or '').strip().lower()
            review_reason = str(review_reason or '').strip()
            reviewed_by = str(reviewed_by or '').strip() or None

            if review_status not in REVIEW_STATUSES:
                return False, 'Review status must be pending, resolved, or ignored'

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

            missing_ppe = [item.strip().lower() for item in (row[0] or '').split(',') if item.strip()]
            if review_status == 'ignored' and not review_reason:
                c.close()
                conn.close()
                return False, 'Review reason is required when ignoring a violation'
            if review_status == 'resolved' and 'helmet' in missing_ppe and not review_reason:
                c.close()
                conn.close()
                return False, 'Helmet reason is required before resolving this violation'
            if review_status == 'resolved' and 'helmet' in missing_ppe and (row[1] != 'worker_submitted' or not row[2]):
                c.close()
                conn.close()
                return False, 'Worker acknowledgement and proof photo are required before resolving this helmet violation'

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
            ''', (instance_id, row[1] or 'pending', review_status, review_reason or None, reviewed_by))
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

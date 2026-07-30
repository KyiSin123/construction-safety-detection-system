import os
from datetime import datetime, timedelta

import mysql.connector


INSTANCE_IDENTITY_COLUMNS = {
    'worker_number': 'VARCHAR(64)',
    'worker_name': 'VARCHAR(255)',
    'worker_team': 'VARCHAR(255)',
    'identity_confidence': 'REAL DEFAULT 0',
    'identity_status': "VARCHAR(64) DEFAULT 'unknown'",
    'identity_source': 'VARCHAR(64)',
    'identity_raw_response': 'TEXT',
    'notification_status': "VARCHAR(64) DEFAULT 'not_sent'",
    'notification_error': 'TEXT',
}
INSTANCE_REVIEW_COLUMNS = {
    'review_status': "ENUM('pending', 'worker_submitted', 'resolved') DEFAULT 'pending'",
    'review_reason': 'TEXT',
    'reviewed_by': 'VARCHAR(255)',
    'review_updated_at': 'DATETIME',
}
INSTANCE_ASSIGNMENT_COLUMNS = {
    'assigned_by_supervisor_id': 'INT NULL',
    'assigned_by_name': 'VARCHAR(255) NULL',
    'assigned_at': 'DATETIME NULL',
}
REVIEW_STATUSES = {'pending', 'worker_submitted', 'resolved'}
BLOCKING_REVIEW_STATUSES = {'pending', 'worker_submitted'}


class Database:
    """Database handler for detections and alerts."""

    def __init__(self):
        self.config = {
            'host': os.getenv('MYSQL_HOST', 'localhost'),
            'port': int(os.getenv('MYSQL_PORT', '3306')),
            'user': os.getenv('MYSQL_USER', 'root'),
            'password': os.getenv('MYSQL_PASSWORD', ''),
            'database': os.getenv('MYSQL_DATABASE', 'helmet_detection'),
        }

    def _connect(self, include_database=True):
        config = self.config.copy()
        if not include_database:
            config.pop('database', None)
        return mysql.connector.connect(**config)

    def init_db(self):
        """Initialize database tables."""
        try:
            server_conn = self._connect(include_database=False)
            server_cursor = server_conn.cursor()
            database_name = self.config['database'].replace('`', '``')
            server_cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{database_name}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
            server_conn.commit()
            server_cursor.close()
            server_conn.close()

            conn = self._connect()
            c = conn.cursor()

            c.execute('''
                CREATE TABLE IF NOT EXISTS instances (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    instance_id VARCHAR(255) UNIQUE,
                    first_detected DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP,
                    is_compliant BOOLEAN DEFAULT 0,
                    missing_ppe TEXT,
                    detected_ppe TEXT
                )
            ''')

            c.execute('''
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    instance_id VARCHAR(255),
                    snapshot_path TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (instance_id) REFERENCES instances(instance_id)
                )
            ''')

            c.execute('''
                CREATE TABLE IF NOT EXISTS workers (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    worker_number VARCHAR(64) UNIQUE NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    team VARCHAR(255),
                    password_hash VARCHAR(255),
                    phone VARCHAR(32),
                    email VARCHAR(255),
                    profile_photo_path TEXT,
                    is_active BOOLEAN DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            c.execute('''
                CREATE TABLE IF NOT EXISTS supervisors (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(64) UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    display_name VARCHAR(255) NOT NULL,
                    role ENUM('admin', 'supervisor') DEFAULT 'supervisor',
                    is_active BOOLEAN DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            c.execute('''
                CREATE TABLE IF NOT EXISTS supervisor_worker_assignments (
                    supervisor_id INT NOT NULL,
                    worker_number VARCHAR(64) NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (supervisor_id, worker_number),
                    FOREIGN KEY (supervisor_id) REFERENCES supervisors(id) ON DELETE CASCADE
                )
            ''')

            c.execute('''
                CREATE TABLE IF NOT EXISTS supervisor_team_assignments (
                    supervisor_id INT NOT NULL,
                    team VARCHAR(255) NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (supervisor_id, team),
                    FOREIGN KEY (supervisor_id) REFERENCES supervisors(id) ON DELETE CASCADE
                )
            ''')

            c.execute('''
                CREATE TABLE IF NOT EXISTS supervisor_devices (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    supervisor_id INT NOT NULL,
                    expo_push_token VARCHAR(255) UNIQUE NOT NULL,
                    platform VARCHAR(32),
                    is_active BOOLEAN DEFAULT 1,
                    last_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (supervisor_id) REFERENCES supervisors(id) ON DELETE CASCADE
                )
            ''')

            c.execute('''
                CREATE TABLE IF NOT EXISTS worker_devices (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    worker_number VARCHAR(64) NOT NULL,
                    expo_push_token VARCHAR(255) UNIQUE NOT NULL,
                    platform VARCHAR(32),
                    is_active BOOLEAN DEFAULT 1,
                    last_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (worker_number) REFERENCES workers(worker_number) ON DELETE CASCADE
                )
            ''')

            c.execute('''
                CREATE TABLE IF NOT EXISTS violation_notifications (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    instance_id VARCHAR(255) NOT NULL,
                    supervisor_id INT NOT NULL,
                    delivery_status VARCHAR(32) DEFAULT 'queued',
                    delivery_error TEXT,
                    notified_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    is_read BOOLEAN NOT NULL DEFAULT 0,
                    read_at DATETIME NULL,
                    UNIQUE KEY unique_violation_supervisor (instance_id, supervisor_id),
                    FOREIGN KEY (instance_id) REFERENCES instances(instance_id) ON DELETE CASCADE,
                    FOREIGN KEY (supervisor_id) REFERENCES supervisors(id) ON DELETE CASCADE
                )
            ''')

            c.execute('''
                CREATE TABLE IF NOT EXISTS worker_violation_notifications (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    instance_id VARCHAR(255) NOT NULL,
                    worker_number VARCHAR(64) NOT NULL,
                    delivery_status VARCHAR(32) DEFAULT 'queued',
                    delivery_error TEXT,
                    notified_at DATETIME NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY unique_worker_violation_notification (instance_id),
                    FOREIGN KEY (instance_id) REFERENCES instances(instance_id) ON DELETE CASCADE,
                    FOREIGN KEY (worker_number) REFERENCES workers(worker_number) ON DELETE CASCADE
                )
            ''')

            c.execute('''
                CREATE TABLE IF NOT EXISTS violation_review_events (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    instance_id VARCHAR(255) NOT NULL,
                    previous_status VARCHAR(32),
                    review_status VARCHAR(32) NOT NULL,
                    review_reason TEXT,
                    supervisor_id INT NULL,
                    reviewer_name VARCHAR(255),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (instance_id) REFERENCES instances(instance_id) ON DELETE CASCADE,
                    FOREIGN KEY (supervisor_id) REFERENCES supervisors(id) ON DELETE SET NULL
                )
            ''')

            c.execute('''
                CREATE TABLE IF NOT EXISTS worker_proof_submissions (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    instance_id VARCHAR(255) NOT NULL,
                    worker_number VARCHAR(64) NOT NULL,
                    comment TEXT NOT NULL,
                    proof_path TEXT NOT NULL,
                    submitted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (instance_id) REFERENCES instances(instance_id) ON DELETE CASCADE,
                    FOREIGN KEY (worker_number) REFERENCES workers(worker_number) ON DELETE CASCADE,
                    INDEX worker_proof_instance (instance_id, submitted_at)
                )
            ''')

            c.execute('''
                CREATE TABLE IF NOT EXISTS attendance_records (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    worker_number VARCHAR(64) NOT NULL,
                    attendance_date DATE NOT NULL,
                    check_in_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    check_out_at DATETIME NULL,
                    recorded_by VARCHAR(255),
                    check_in_reason TEXT,
                    check_out_reason TEXT,
                    UNIQUE KEY unique_worker_attendance_day (worker_number, attendance_date),
                    FOREIGN KEY (worker_number) REFERENCES workers(worker_number)
                )
            ''')

            c.execute('''
                CREATE TABLE IF NOT EXISTS attendance_requests (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    worker_number VARCHAR(64) NOT NULL,
                    action ENUM('check_in', 'check_out') NOT NULL,
                    requested_at DATETIME NOT NULL,
                    reason TEXT NOT NULL,
                    status ENUM('pending', 'approved', 'rejected') NOT NULL DEFAULT 'pending',
                    reviewed_by INT NULL,
                    reviewer_name VARCHAR(255),
                    decision_reason TEXT,
                    decided_at DATETIME NULL,
                    attendance_record_id INT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (worker_number) REFERENCES workers(worker_number) ON DELETE CASCADE,
                    FOREIGN KEY (reviewed_by) REFERENCES supervisors(id) ON DELETE SET NULL,
                    FOREIGN KEY (attendance_record_id) REFERENCES attendance_records(id) ON DELETE SET NULL,
                    INDEX attendance_request_worker_status (worker_number, status),
                    INDEX attendance_request_requested_at (requested_at)
                )
            ''')

            self._ensure_instance_columns(c)
            self._ensure_violation_notification_columns(c)
            self._ensure_worker_columns(c)
            self._ensure_worker_submission_columns(c)
            self._ensure_attendance_columns(c)

            conn.commit()
            c.close()
            conn.close()
        except Exception as e:
            print(f"Error initializing database: {e}")

    def _ensure_attendance_columns(self, cursor):
        cursor.execute('''
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'attendance_records'
        ''', (self.config['database'],))
        existing_columns = {row[0] for row in cursor.fetchall()}
        for column in ('check_in_reason', 'check_out_reason'):
            if column not in existing_columns:
                cursor.execute(f'ALTER TABLE attendance_records ADD COLUMN {column} TEXT')

    def _ensure_instance_columns(self, cursor):
        cursor.execute('''
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'instances'
        ''', (self.config['database'],))
        existing_columns = {row[0] for row in cursor.fetchall()}
        for column, column_type in {
            **INSTANCE_IDENTITY_COLUMNS, **INSTANCE_REVIEW_COLUMNS, **INSTANCE_ASSIGNMENT_COLUMNS
        }.items():
            if column not in existing_columns:
                cursor.execute(f'ALTER TABLE instances ADD COLUMN {column} {column_type}')
        if 'review_status' in existing_columns:
            cursor.execute("UPDATE instances SET review_status = 'resolved' WHERE review_status = 'ignored'")
            cursor.execute(
                "ALTER TABLE instances MODIFY COLUMN review_status "
                "ENUM('pending', 'worker_submitted', 'resolved') DEFAULT 'pending'"
            )

    def _ensure_violation_notification_columns(self, cursor):
        cursor.execute('''
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'violation_notifications'
        ''', (self.config['database'],))
        existing_columns = {row[0] for row in cursor.fetchall()}
        if 'is_read' not in existing_columns:
            cursor.execute('ALTER TABLE violation_notifications ADD COLUMN is_read BOOLEAN NOT NULL DEFAULT 0')
        if 'read_at' not in existing_columns:
            cursor.execute('ALTER TABLE violation_notifications ADD COLUMN read_at DATETIME NULL')

    def _ensure_worker_columns(self, cursor):
        cursor.execute('''SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'workers' ''', (self.config['database'],))
        existing = {row[0] for row in cursor.fetchall()}
        for column, column_type in {
            'password_hash': 'VARCHAR(255) NULL',
            'phone': 'VARCHAR(32) NULL',
            'email': 'VARCHAR(255) NULL',
            'profile_photo_path': 'TEXT NULL',
        }.items():
            if column not in existing:
                cursor.execute(f'ALTER TABLE workers ADD COLUMN {column} {column_type}')

    def _ensure_worker_submission_columns(self, cursor):
        cursor.execute('''SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'instances' ''', (self.config['database'],))
        existing = {row[0] for row in cursor.fetchall()}
        for name, definition in {'worker_acknowledged_at':'DATETIME NULL','worker_comment':'TEXT','worker_proof_path':'TEXT','worker_proof_at':'DATETIME NULL'}.items():
            if name not in existing: cursor.execute(f'ALTER TABLE instances ADD COLUMN {name} {definition}')

    def _format_datetime(self, value):
        if isinstance(value, datetime):
            return value.isoformat(sep=' ')
        return value

    def _normalize_missing_ppe(self, missing_ppe):
        if isinstance(missing_ppe, str):
            items = missing_ppe.split(',')
        else:
            items = missing_ppe or []
        normalized = {
            str(item).strip().lower()
            for item in items
            if str(item).strip()
        }
        return sorted(normalized)

    def _missing_ppe_text(self, missing_ppe):
        return ','.join(self._normalize_missing_ppe(missing_ppe))

    def find_blocking_violation(self, missing_ppe, identity=None):
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
                    SELECT instance_id, missing_ppe
                    FROM instances
                    WHERE is_compliant = 0
                      AND review_status IN (%s, %s)
                      AND DATE(first_detected) = CURDATE()
                      AND worker_number = %s
                    ORDER BY first_detected ASC
                ''', (*blocking_statuses, worker_number))
            else:
                c.execute('''
                    SELECT instance_id, missing_ppe
                    FROM instances
                    WHERE is_compliant = 0
                      AND review_status IN (%s, %s)
                      AND DATE(first_detected) = CURDATE()
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

    def update_notification_status(self, instance_id, status, error=None):
        try:
            conn = self._connect()
            c = conn.cursor()
            c.execute('''
                UPDATE instances
                SET notification_status = %s, notification_error = %s
                WHERE instance_id = %s
            ''', (status, error, instance_id))
            conn.commit()
            c.close()
            conn.close()
            return True
        except Exception as e:
            print(f"Error updating notification status: {e}")
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
                SELECT i.id, i.instance_id, i.first_detected, i.last_updated,
                       i.is_compliant, i.missing_ppe, i.detected_ppe,
                       i.worker_number, i.worker_name, i.worker_team,
                       i.identity_confidence, i.identity_status,
                       i.identity_source, i.identity_raw_response,
                       i.notification_status, i.notification_error,
                       i.review_status, i.review_reason, i.reviewed_by,
                       i.review_updated_at, COALESCE(s.snapshot_count, 0) AS snapshot_count
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
                c.close(); conn.close()
                return False, 'Resolved violations are read-only'
            if review_status == 'worker_submitted':
                c.close(); conn.close()
                return False, 'Only a worker proof submission can set worker_submitted status'
            if review_status == 'resolved' and previous_status == 'pending' and not review_reason:
                c.close()
                conn.close()
                return False, 'A reason is required when resolving directly'
            if review_status == 'resolved' and previous_status == 'worker_submitted' and not row[2]:
                c.close(); conn.close()
                return False, 'Worker proof is required before approval'
            if review_status == 'pending' and previous_status == 'worker_submitted' and not review_reason:
                c.close(); conn.close()
                return False, 'A reason is required when requesting new proof'
            if review_status == previous_status:
                c.close(); conn.close()
                return False, 'Choose a valid review action'

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
                'display_name': row[3], 'role': row[4], 'is_active': bool(row[5])
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
                c.execute('SELECT worker_number FROM supervisor_worker_assignments WHERE supervisor_id = %s', (supervisor['id'],))
                supervisor['worker_numbers'] = [row[0] for row in c.fetchall()]
                c.execute('SELECT team FROM supervisor_team_assignments WHERE supervisor_id = %s', (supervisor['id'],))
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
                query = '''UPDATE supervisors SET username = %s, display_name = %s, role = %s,
                           is_active = %s, updated_at = CURRENT_TIMESTAMP'''
                params = [username, display_name, role, 1 if payload.get('is_active', True) else 0]
                if password_hash:
                    query += ', password_hash = %s'
                    params.append(password_hash)
                query += ' WHERE id = %s'
                params.append(supervisor_id)
                c.execute(query, tuple(params))
            else:
                if not password_hash:
                    c.close(); conn.close()
                    return False, 'Password is required for a new supervisor', None
                c.execute('''INSERT INTO supervisors (username, password_hash, display_name, role, is_active)
                             VALUES (%s, %s, %s, %s, %s)''',
                          (username, password_hash, display_name, role, 1 if payload.get('is_active', True) else 0))
                supervisor_id = c.lastrowid
            conn.commit()
            c.close(); conn.close()
            return True, 'Supervisor saved', supervisor_id
        except Exception as e:
            print(f"Error saving supervisor: {e}")
            return False, str(e), None

    def set_supervisor_assignments(self, supervisor_id, worker_numbers=None, teams=None):
        worker_numbers = sorted({str(value).strip().upper() for value in (worker_numbers or []) if str(value).strip()})
        teams = sorted({str(value).strip() for value in (teams or []) if str(value).strip()})
        try:
            conn = self._connect(); c = conn.cursor()
            c.execute('DELETE FROM supervisor_worker_assignments WHERE supervisor_id = %s', (supervisor_id,))
            c.execute('DELETE FROM supervisor_team_assignments WHERE supervisor_id = %s', (supervisor_id,))
            if worker_numbers:
                c.executemany('INSERT INTO supervisor_worker_assignments (supervisor_id, worker_number) VALUES (%s, %s)',
                              [(supervisor_id, value) for value in worker_numbers])
            if teams:
                c.executemany('INSERT INTO supervisor_team_assignments (supervisor_id, team) VALUES (%s, %s)',
                              [(supervisor_id, value) for value in teams])
            conn.commit(); c.close(); conn.close()
            return True, 'Assignments saved'
        except Exception as e:
            print(f"Error saving assignments: {e}")
            return False, str(e)

    def register_supervisor_device(self, supervisor_id, expo_push_token, platform=None):
        try:
            conn = self._connect(); c = conn.cursor()
            c.execute('''
                INSERT INTO supervisor_devices (supervisor_id, expo_push_token, platform, is_active)
                VALUES (%s, %s, %s, 1)
                ON DUPLICATE KEY UPDATE supervisor_id = VALUES(supervisor_id), platform = VALUES(platform),
                    is_active = 1, last_seen_at = CURRENT_TIMESTAMP
            ''', (supervisor_id, expo_push_token, platform))
            conn.commit(); c.close(); conn.close()
            return True, 'Device registered'
        except Exception as e:
            print(f"Error registering device: {e}")
            return False, str(e)

    def deactivate_supervisor_device(self, supervisor_id, expo_push_token=None):
        try:
            conn = self._connect(); c = conn.cursor()
            query = 'UPDATE supervisor_devices SET is_active = 0 WHERE supervisor_id = %s'
            params = [supervisor_id]
            if expo_push_token:
                query += ' AND expo_push_token = %s'; params.append(expo_push_token)
            c.execute(query, tuple(params)); conn.commit(); c.close(); conn.close()
            return True
        except Exception as e:
            print(f"Error deactivating device: {e}")
            return False

    def get_active_supervisor_devices(self, supervisor_id):
        try:
            conn = self._connect(); c = conn.cursor()
            c.execute('''
                SELECT expo_push_token FROM supervisor_devices
                WHERE supervisor_id = %s AND is_active = 1
            ''', (supervisor_id,))
            tokens = [row[0] for row in c.fetchall()]
            c.close(); conn.close()
            return tokens
        except Exception as e:
            print(f"Error getting supervisor devices: {e}")
            return []

    def register_worker_device(self, worker_number, expo_push_token, platform=None):
        try:
            conn = self._connect(); c = conn.cursor()
            c.execute('''
                INSERT INTO worker_devices (worker_number, expo_push_token, platform, is_active)
                VALUES (%s, %s, %s, 1)
                ON DUPLICATE KEY UPDATE worker_number = VALUES(worker_number), platform = VALUES(platform),
                    is_active = 1, last_seen_at = CURRENT_TIMESTAMP
            ''', (worker_number, expo_push_token, platform))
            conn.commit(); c.close(); conn.close()
            return True, 'Worker device registered'
        except Exception as e:
            print(f"Error registering worker device: {e}")
            return False, str(e)

    def deactivate_worker_device(self, worker_number, expo_push_token=None):
        try:
            conn = self._connect(); c = conn.cursor()
            query = 'UPDATE worker_devices SET is_active = 0 WHERE worker_number = %s'
            params = [worker_number]
            if expo_push_token:
                query += ' AND expo_push_token = %s'; params.append(expo_push_token)
            c.execute(query, tuple(params))
            conn.commit(); c.close(); conn.close()
            return True
        except Exception as e:
            print(f"Error deactivating worker device: {e}")
            return False

    def search_active_workers(self, search=''):
        try:
            search = str(search or '').strip()
            conn = self._connect(); c = conn.cursor()
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
            rows = c.fetchall(); c.close(); conn.close()
            return [{'worker_number': row[0], 'name': row[1], 'team': row[2]} for row in rows]
        except Exception as e:
            print(f"Error searching workers: {e}")
            return []

    def assign_worker_to_violation(self, supervisor, instance_id, worker_number):
        """Atomically assign the first confirmed worker and create one logical push record."""
        worker_number = str(worker_number or '').strip().upper()
        conn = None
        try:
            conn = self._connect(); c = conn.cursor()
            c.execute('''
                SELECT 1 FROM violation_notifications
                WHERE supervisor_id = %s AND instance_id = %s
            ''', (supervisor['id'], instance_id))
            if not c.fetchone():
                conn.rollback(); c.close(); conn.close()
                return False, 'This violation is not assigned to you', None
            c.execute('''
                SELECT worker_number, identity_status, review_status FROM instances
                WHERE instance_id = %s FOR UPDATE
            ''', (instance_id,))
            instance = c.fetchone()
            if not instance:
                conn.rollback(); c.close(); conn.close()
                return False, 'Violation not found', None
            if instance[2] != 'pending':
                conn.rollback(); c.close(); conn.close()
                return False, 'Only pending violations can be assigned', None
            if instance[0] or instance[1] == 'confirmed':
                conn.rollback(); c.close(); conn.close()
                return False, 'This violation has already been assigned', None
            c.execute('''
                SELECT worker_number, name, team FROM workers
                WHERE worker_number = %s AND is_active = 1
            ''', (worker_number,))
            worker = c.fetchone()
            if not worker:
                conn.rollback(); c.close(); conn.close()
                return False, 'Choose an active worker', None
            c.execute('''
                UPDATE instances SET worker_number = %s, worker_name = %s, worker_team = %s,
                    identity_status = 'confirmed', identity_source = 'supervisor_manual',
                    identity_confidence = 1, assigned_by_supervisor_id = %s,
                    assigned_by_name = %s, assigned_at = CURRENT_TIMESTAMP,
                    last_updated = CURRENT_TIMESTAMP
                WHERE instance_id = %s
            ''', (worker[0], worker[1], worker[2], supervisor['id'],
                  supervisor['display_name'], instance_id))
            c.execute('''
                INSERT INTO violation_review_events
                    (instance_id, previous_status, review_status, review_reason,
                     supervisor_id, reviewer_name)
                VALUES (%s, 'pending', 'pending', %s, %s, %s)
            ''', (instance_id, f'Manually assigned to {worker[1]} ({worker[0]})',
                  supervisor['id'], supervisor['display_name']))
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
            conn.commit(); c.close(); conn.close()
            return True, 'Worker assigned', {
                'notification_id': notification_id, 'worker_number': worker[0],
                'worker_name': worker[1], 'worker_team': worker[2], 'tokens': tokens,
            }
        except Exception as e:
            if conn:
                try: conn.rollback(); conn.close()
                except Exception: pass
            print(f"Error assigning worker: {e}")
            return False, str(e), None

    def update_worker_notification_status(self, notification_id, status, error=None):
        try:
            conn = self._connect(); c = conn.cursor()
            c.execute('''
                UPDATE worker_violation_notifications
                SET delivery_status = %s, delivery_error = %s, notified_at = CURRENT_TIMESTAMP
                WHERE id = %s
            ''', (status, error, notification_id))
            conn.commit(); c.close(); conn.close()
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
            conn = self._connect(); c = conn.cursor()
            if unknown_identity:
                c.execute('SELECT id FROM supervisors WHERE is_active = 1')
            else:
                clauses, params = [], []
                if worker_number:
                    clauses.append('swa.worker_number = %s'); params.append(worker_number)
                if team:
                    clauses.append('sta.team = %s'); params.append(team)
                c.execute(f'''
                    SELECT DISTINCT s.id
                    FROM supervisors s
                    LEFT JOIN supervisor_worker_assignments swa ON swa.supervisor_id = s.id
                    LEFT JOIN supervisor_team_assignments sta ON sta.supervisor_id = s.id
                    WHERE s.is_active = 1 AND ({' OR '.join(clauses)})
                ''', tuple(params))
            recipient_ids = [row[0] for row in c.fetchall()]
            if not recipient_ids:
                c.close(); conn.close(); return []
            placeholders = ','.join(['%s'] * len(recipient_ids))
            c.execute(f'SELECT supervisor_id FROM violation_notifications WHERE instance_id = %s AND supervisor_id IN ({placeholders})',
                      (instance_id, *recipient_ids))
            existing = {row[0] for row in c.fetchall()}
            created_ids = [value for value in recipient_ids if value not in existing]
            if created_ids:
                c.executemany('INSERT INTO violation_notifications (instance_id, supervisor_id) VALUES (%s, %s)',
                              [(instance_id, value) for value in created_ids])
            if not created_ids:
                conn.commit(); c.close(); conn.close(); return []
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
            conn.commit(); c.close(); conn.close()
            return rows
        except Exception as e:
            print(f"Error creating supervisor notifications: {e}")
            return []

    def update_supervisor_notification_status(self, notification_id, status, error=None):
        try:
            conn = self._connect(); c = conn.cursor()
            c.execute('''UPDATE violation_notifications SET delivery_status = %s, delivery_error = %s,
                         notified_at = CURRENT_TIMESTAMP WHERE id = %s''', (status, error, notification_id))
            conn.commit(); c.close(); conn.close()
        except Exception as e:
            print(f"Error updating supervisor notification: {e}")

    def ensure_unknown_violation_access(self, supervisor_id):
        """Make prior unknown-worker records visible without treating them as a new push alert."""
        try:
            conn = self._connect(); c = conn.cursor()
            c.execute('''
                INSERT IGNORE INTO violation_notifications (instance_id, supervisor_id, delivery_status)
                SELECT i.instance_id, %s, 'historical'
                FROM instances i
                WHERE i.is_compliant = 0
                  AND (i.worker_number IS NULL OR i.worker_number = ''
                       OR i.identity_status IS NULL OR i.identity_status != 'confirmed')
            ''', (supervisor_id,))
            conn.commit(); c.close(); conn.close()
        except Exception as e:
            print(f"Error backfilling unknown violations: {e}")

    def get_mobile_violations(self, supervisor_id, status='pending'):
        if status not in REVIEW_STATUSES:
            status = 'pending'
        try:
            self.ensure_unknown_violation_access(supervisor_id)
            conn = self._connect(); c = conn.cursor()
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
            rows = c.fetchall(); c.close(); conn.close()
            return [self._mobile_violation_from_row(row) for row in rows]
        except Exception as e:
            print(f"Error getting mobile violations: {e}")
            return []

    def get_mobile_violation_counts(self, supervisor_id):
        try:
            self.ensure_unknown_violation_access(supervisor_id)
            conn = self._connect(); c = conn.cursor()
            c.execute('''
                SELECT i.review_status, COUNT(DISTINCT i.instance_id)
                FROM violation_notifications n
                JOIN instances i ON i.instance_id = n.instance_id
                WHERE n.supervisor_id = %s
                  AND i.review_status IN ('pending', 'worker_submitted', 'resolved')
                GROUP BY i.review_status
            ''', (supervisor_id,))
            counts = {'pending': 0, 'worker_submitted': 0, 'resolved': 0}
            for status, count in c.fetchall():
                if status in counts:
                    counts[status] = count
            c.close(); conn.close()
            return counts
        except Exception as e:
            print(f"Error getting mobile violation counts: {e}")
            return {'pending': 0, 'worker_submitted': 0, 'resolved': 0}

    def get_mobile_violation_detail(self, supervisor_id, instance_id):
        try:
            conn = self._connect(); c = conn.cursor()
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
                c.close(); conn.close(); return None
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
            c.execute('''SELECT worker_comment, worker_proof_at
                         FROM instances WHERE instance_id = %s''', (instance_id,))
            proof = c.fetchone()
            result['worker_comment'] = proof[0] if proof else None
            result['worker_proof_at'] = self._format_datetime(proof[1]) if proof else None
            c.execute('SELECT id, timestamp FROM snapshots WHERE instance_id = %s ORDER BY timestamp ASC', (instance_id,))
            result['snapshots'] = [{'id': value[0], 'timestamp': self._format_datetime(value[1])} for value in c.fetchall()]
            c.execute('''SELECT previous_status, review_status, review_reason, reviewer_name, created_at
                         FROM violation_review_events WHERE instance_id = %s ORDER BY created_at DESC''', (instance_id,))
            result['review_events'] = [
                {'previous_status': value[0], 'review_status': value[1], 'review_reason': value[2],
                 'reviewed_by': value[3], 'created_at': self._format_datetime(value[4])}
                for value in c.fetchall()
            ]
            c.close(); conn.close(); return result
        except Exception as e:
            print(f"Error getting mobile violation: {e}")
            return None

    def get_mobile_snapshot_path(self, supervisor_id, snapshot_id):
        try:
            conn = self._connect(); c = conn.cursor()
            c.execute('''
                SELECT s.snapshot_path FROM snapshots s
                JOIN violation_notifications n ON n.instance_id = s.instance_id
                WHERE s.id = %s AND n.supervisor_id = %s
            ''', (snapshot_id, supervisor_id))
            row = c.fetchone(); c.close(); conn.close()
            return row[0] if row else None
        except Exception as e:
            print(f"Error getting mobile snapshot: {e}")
            return None

    def get_worker_proof_path(self, supervisor_id, instance_id):
        try:
            conn=self._connect(); c=conn.cursor(); c.execute('''SELECT i.worker_proof_path FROM instances i JOIN violation_notifications n ON n.instance_id=i.instance_id WHERE n.supervisor_id=%s AND i.instance_id=%s''',(supervisor_id,instance_id)); row=c.fetchone(); c.close(); conn.close(); return row[0] if row else None
        except Exception as e: print(f'Error getting worker proof: {e}'); return None

    def get_mobile_unread_notification_count(self, supervisor_id):
        try:
            conn = self._connect(); c = conn.cursor()
            c.execute('''SELECT COUNT(*) FROM violation_notifications
                         WHERE supervisor_id = %s AND is_read = 0''', (supervisor_id,))
            count = c.fetchone()[0]
            c.close(); conn.close()
            return count
        except Exception as e:
            print(f"Error counting unread notifications: {e}")
            return 0

    def mark_mobile_notification_read(self, supervisor_id, instance_id=None):
        try:
            conn = self._connect(); c = conn.cursor()
            query = '''UPDATE violation_notifications SET is_read = 1, read_at = COALESCE(read_at, CURRENT_TIMESTAMP)
                       WHERE supervisor_id = %s AND is_read = 0'''
            params = [supervisor_id]
            if instance_id:
                query += ' AND instance_id = %s'; params.append(instance_id)
            c.execute(query, tuple(params))
            updated = c.rowcount
            conn.commit(); c.close(); conn.close()
            return True, updated
        except Exception as e:
            print(f"Error marking notifications read: {e}")
            return False, 0

    def update_mobile_review(self, supervisor, instance_id, review_status, review_reason=None):
        supervisor_id = supervisor.get('id')
        try:
            conn = self._connect(); c = conn.cursor()
            c.execute('''SELECT i.worker_number, i.identity_status
                         FROM violation_notifications n
                         JOIN instances i ON i.instance_id = n.instance_id
                         WHERE n.supervisor_id = %s AND n.instance_id = %s''',
                      (supervisor_id, instance_id))
            violation = c.fetchone()
            c.close(); conn.close()
            if not violation:
                return False, 'This violation is not assigned to you', None
            ok, message = self.update_instance_review(instance_id, review_status, review_reason, supervisor.get('display_name'))
            if ok:
                conn = self._connect(); c = conn.cursor()
                c.execute('''UPDATE violation_review_events SET supervisor_id = %s
                             WHERE instance_id = %s ORDER BY id DESC LIMIT 1''', (supervisor_id, instance_id))
                action = {'review_status': str(review_status).strip().lower()}
                if action['review_status'] == 'pending':
                    c.execute('''SELECT d.expo_push_token
                                 FROM instances i JOIN worker_devices d ON d.worker_number=i.worker_number
                                 WHERE i.instance_id=%s AND d.is_active=1''', (instance_id,))
                    action['worker_tokens'] = [row[0] for row in c.fetchall()]
                conn.commit(); c.close(); conn.close()
                return True, message, action
            return False, message, None
        except Exception as e:
            print(f"Error updating mobile review: {e}")
            return False, str(e), None

    def _supervisor_from_row(self, row):
        return {
            'id': row[0], 'username': row[1], 'display_name': row[2],
            'role': row[3], 'is_active': bool(row[4])
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
            'worker_proof_at': self._format_datetime(row[19]) if len(row) > 19 else None,
        }

    def record_attendance(self, worker_number, action, recorded_by=None, recorded_at=None, reason=None):
        worker_number = str(worker_number or '').strip().upper()
        action = str(action or '').strip().lower()
        reason = str(reason or '').strip()
        if action not in {'check_in', 'check_out'}:
            return False, 'Choose check-in or check-out', None
        if not reason:
            return False, 'Reason is required for attendance entered by an admin', None
        try:
            recorded_at = datetime.fromisoformat(str(recorded_at or '').strip())
        except (TypeError, ValueError):
            return False, 'Select a valid attendance date and time', None
        if recorded_at.tzinfo is not None:
            recorded_at = recorded_at.replace(tzinfo=None)
        attendance_date = recorded_at.date()
        try:
            conn = self._connect(); c = conn.cursor()
            c.execute('SELECT worker_number, name, team FROM workers WHERE worker_number = %s AND is_active = 1', (worker_number,))
            worker = c.fetchone()
            if not worker:
                c.close(); conn.close(); return False, 'Worker ID is not registered or is inactive', None
            c.execute('''SELECT id, check_in_at, check_out_at FROM attendance_records
                         WHERE worker_number = %s AND attendance_date = %s''', (worker_number, attendance_date))
            record = c.fetchone()
            if action == 'check_in':
                if record:
                    message = 'Worker is already checked in today' if record[2] is None else 'Worker attendance is already completed today'
                    c.close(); conn.close(); return False, message, None
                c.execute('''INSERT INTO attendance_records
                             (worker_number, attendance_date, check_in_at, recorded_by, check_in_reason)
                             VALUES (%s, %s, %s, %s, %s)''',
                          (worker_number, attendance_date, recorded_at, recorded_by, reason))
                message = 'Check-in recorded'
            else:
                if not record:
                    c.close(); conn.close(); return False, 'No check-in record exists for today', None
                if record[2] is not None:
                    c.close(); conn.close(); return False, 'Worker is already checked out today', None
                if recorded_at < record[1]:
                    c.close(); conn.close(); return False, 'Check-out time cannot be before check-in time', None
                c.execute('''UPDATE attendance_records
                             SET check_out_at = %s, recorded_by = %s, check_out_reason = %s WHERE id = %s''',
                          (recorded_at, recorded_by, reason, record[0]))
                message = 'Check-out recorded'
            conn.commit(); c.close(); conn.close()
            return True, message, {'worker_number': worker[0], 'name': worker[1], 'team': worker[2]}
        except Exception as e:
            print(f"Error recording attendance: {e}")
            return False, str(e), None

    def get_attendance(self, attendance_date=None):
        try:
            conn = self._connect(); c = conn.cursor()
            if attendance_date:
                c.execute('''SELECT a.id, a.worker_number, w.name, w.team, a.attendance_date, a.check_in_at, a.check_out_at, a.recorded_by, a.check_in_reason, a.check_out_reason
                             FROM attendance_records a JOIN workers w ON w.worker_number = a.worker_number
                             WHERE a.attendance_date = %s ORDER BY a.check_in_at DESC''', (attendance_date,))
            else:
                c.execute('''SELECT a.id, a.worker_number, w.name, w.team, a.attendance_date, a.check_in_at, a.check_out_at, a.recorded_by, a.check_in_reason, a.check_out_reason
                             FROM attendance_records a JOIN workers w ON w.worker_number = a.worker_number
                             WHERE a.attendance_date = CURDATE() ORDER BY a.check_in_at DESC''')
            records = [{'id': row[0], 'worker_number': row[1], 'name': row[2], 'team': row[3],
                        'attendance_date': str(row[4]), 'check_in_at': self._format_datetime(row[5]),
                        'check_out_at': self._format_datetime(row[6]), 'recorded_by': row[7],
                        'check_in_reason': row[8], 'check_out_reason': row[9]} for row in c.fetchall()]
            c.close(); conn.close(); return records
        except Exception as e:
            print(f"Error getting attendance: {e}")
            return []

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
            conn=self._connect(); c=conn.cursor(); c.execute('''SELECT worker_number, name, team, password_hash,
                is_active, phone, email, profile_photo_path FROM workers WHERE worker_number = %s''',
                (str(worker_number or '').strip().upper(),)); row=c.fetchone(); c.close(); conn.close()
            return {'worker_number':row[0],'name':row[1],'team':row[2],'password_hash':row[3],
                    'is_active':bool(row[4]),'phone':row[5],'email':row[6],
                    'profile_photo_path':row[7]} if row else None
        except Exception as e: print(f'Error getting worker login: {e}'); return None

    @staticmethod
    def _page_values(page, per_page):
        try: page = max(1, int(page or 1))
        except (TypeError, ValueError): page = 1
        try: per_page = min(50, max(1, int(per_page or 20)))
        except (TypeError, ValueError): per_page = 20
        return page, per_page

    def worker_violations(self, worker_number, page=1, per_page=20, status=None, ppe=None):
        try:
            page,per_page=self._page_values(page,per_page); clauses=["worker_number=%s","identity_status='confirmed'"]; params=[worker_number]
            if status in REVIEW_STATUSES: clauses.append('review_status=%s'); params.append(status)
            if ppe: clauses.append('FIND_IN_SET(%s, LOWER(missing_ppe)) > 0'); params.append(str(ppe).strip().lower())
            where=' AND '.join(clauses); conn=self._connect(); c=conn.cursor()
            c.execute(f'SELECT COUNT(*) FROM instances WHERE {where}',tuple(params)); total=c.fetchone()[0]
            c.execute(f'''SELECT instance_id, first_detected, missing_ppe, review_status, worker_comment,
                worker_proof_path, worker_proof_at, review_reason, reviewed_by, review_updated_at
                FROM instances WHERE {where} ORDER BY first_detected DESC LIMIT %s OFFSET %s''',
                tuple(params+[per_page,(page-1)*per_page])); rows=c.fetchall(); c.close(); conn.close()
            items=[{'instance_id':r[0],'first_detected':self._format_datetime(r[1]),
                'missing_ppe':[v for v in (r[2] or '').split(',') if v],'review_status':r[3],
                'worker_comment':r[4],'has_proof':bool(r[5]),'worker_proof_at':self._format_datetime(r[6]),
                'review_reason':r[7],'reviewed_by':r[8],'review_updated_at':self._format_datetime(r[9])} for r in rows]
            return {'items':items,'page':page,'per_page':per_page,'total':total,'has_more':page*per_page<total}
        except Exception as e: print(f'Error getting worker violations: {e}'); return {'items':[],'page':1,'per_page':20,'total':0,'has_more':False}

    def worker_violation_counts(self, worker_number):
        try:
            conn=self._connect(); c=conn.cursor()
            c.execute('''SELECT review_status,COUNT(*) FROM instances
                WHERE worker_number=%s AND identity_status='confirmed'
                  AND review_status IN ('pending','worker_submitted','resolved')
                GROUP BY review_status''',(worker_number,))
            counts={'pending':0,'worker_submitted':0,'resolved':0}
            for status,count in c.fetchall():
                if status in counts: counts[status]=count
            c.close(); conn.close(); return counts
        except Exception as e:
            print(f'Error getting worker violation counts: {e}')
            return {'pending':0,'worker_submitted':0,'resolved':0}

    def worker_attendance(self, worker_number, page=1, per_page=20, month=None, attendance_date=None):
        try:
            page,per_page=self._page_values(page,per_page); clauses=['a.worker_number=%s']; params=[worker_number]
            if attendance_date: clauses.append('a.attendance_date=%s'); params.append(attendance_date)
            elif month: clauses.append("DATE_FORMAT(a.attendance_date, '%Y-%m')=%s"); params.append(month)
            where=' AND '.join(clauses); conn=self._connect(); c=conn.cursor()
            c.execute(f'SELECT COUNT(*) FROM attendance_records a WHERE {where}',tuple(params)); total=c.fetchone()[0]
            c.execute(f'''SELECT a.id,a.attendance_date,a.check_in_at,a.check_out_at,a.recorded_by,
                a.check_in_reason,a.check_out_reason FROM attendance_records a WHERE {where}
                ORDER BY a.attendance_date DESC,a.check_in_at DESC LIMIT %s OFFSET %s''',
                tuple(params+[per_page,(page-1)*per_page])); rows=c.fetchall(); c.close(); conn.close()
            items=[{'id':r[0],'attendance_date':str(r[1]),'check_in_at':self._format_datetime(r[2]),
                'check_out_at':self._format_datetime(r[3]),'recorded_by':r[4],
                'check_in_reason':r[5],'check_out_reason':r[6],
                'status':'completed' if r[3] else 'on_site'} for r in rows]
            return {'items':items,'page':page,'per_page':per_page,'total':total,'has_more':page*per_page<total}
        except Exception as e: print(f'Error getting worker attendance: {e}'); return {'items':[],'page':1,'per_page':20,'total':0,'has_more':False}

    def update_worker_profile(self, worker_number, phone, email, profile_photo_path=None):
        try:
            conn=self._connect(); c=conn.cursor()
            if email:
                c.execute('SELECT worker_number FROM workers WHERE LOWER(email)=LOWER(%s) AND worker_number<>%s',(email,worker_number))
                if c.fetchone(): c.close(); conn.close(); return False,'Email is already in use',None
            query='UPDATE workers SET phone=%s,email=%s,updated_at=CURRENT_TIMESTAMP'; params=[phone or None,email or None]
            if profile_photo_path is not None: query+=',profile_photo_path=%s'; params.append(profile_photo_path)
            query+=' WHERE worker_number=%s'; params.append(worker_number); c.execute(query,tuple(params)); conn.commit(); c.close(); conn.close()
            return True,'Profile updated',self.get_worker_for_login(worker_number)
        except Exception as e: print(f'Error updating worker profile: {e}'); return False,str(e),None

    def update_worker_password(self, worker_number, password_hash):
        try:
            conn=self._connect(); c=conn.cursor(); c.execute(
                'UPDATE workers SET password_hash=%s,updated_at=CURRENT_TIMESTAMP WHERE worker_number=%s',
                (password_hash,worker_number)); conn.commit(); c.close(); conn.close(); return True
        except Exception as e: print(f'Error updating worker password: {e}'); return False

    def create_attendance_request(self, worker_number, action, requested_at, reason):
        action=str(action or '').strip().lower(); reason=str(reason or '').strip()
        if action not in {'check_in','check_out'} or not reason: return False,'Action, date/time, and reason are required',None
        try: requested_at=datetime.fromisoformat(str(requested_at or '').strip()).replace(tzinfo=None)
        except (TypeError,ValueError): return False,'Select a valid requested date and time',None
        try:
            conn=self._connect(); c=conn.cursor(); conn.start_transaction()
            c.execute('SELECT worker_number FROM workers WHERE worker_number=%s FOR UPDATE',(worker_number,))
            if not c.fetchone(): conn.rollback(); c.close(); conn.close(); return False,'Worker not found',None
            c.execute('''SELECT id FROM attendance_requests WHERE worker_number=%s AND action=%s
                AND DATE(requested_at)=%s AND status='pending' LIMIT 1''',(worker_number,action,requested_at.date()))
            if c.fetchone(): c.close(); conn.close(); return False,'A pending request already exists for this date and action',None
            c.execute('''INSERT INTO attendance_requests(worker_number,action,requested_at,reason)
                VALUES(%s,%s,%s,%s)''',(worker_number,action,requested_at,reason)); request_id=c.lastrowid
            conn.commit(); c.close(); conn.close(); return True,'Attendance request submitted',request_id
        except Exception as e: print(f'Error creating attendance request: {e}'); return False,str(e),None

    def worker_attendance_requests(self, worker_number):
        try:
            conn=self._connect(); c=conn.cursor(); c.execute('''SELECT id,action,requested_at,reason,status,
                reviewer_name,decision_reason,decided_at,created_at FROM attendance_requests
                WHERE worker_number=%s ORDER BY created_at DESC''',(worker_number,)); rows=c.fetchall(); c.close(); conn.close()
            return [self._attendance_request_from_row(r) for r in rows]
        except Exception as e: print(f'Error listing worker attendance requests: {e}'); return []

    def _attendance_request_from_row(self, row):
        return {'id':row[0],'action':row[1],'requested_at':self._format_datetime(row[2]),
            'reason':row[3],'status':row[4],'reviewer_name':row[5],'decision_reason':row[6],
            'decided_at':self._format_datetime(row[7]),'created_at':self._format_datetime(row[8])}

    def attendance_request_recipients(self, worker_number):
        try:
            conn=self._connect(); c=conn.cursor(); c.execute('SELECT team FROM workers WHERE worker_number=%s',(worker_number,)); row=c.fetchone()
            team=row[0] if row else None
            c.execute('''SELECT DISTINCT s.id,d.expo_push_token FROM supervisors s
                LEFT JOIN supervisor_devices d ON d.supervisor_id=s.id AND d.is_active=1
                LEFT JOIN supervisor_worker_assignments wa ON wa.supervisor_id=s.id AND wa.worker_number=%s
                LEFT JOIN supervisor_team_assignments ta ON ta.supervisor_id=s.id AND ta.team=%s
                WHERE s.is_active=1 AND (wa.worker_number IS NOT NULL OR ta.team IS NOT NULL)''',(worker_number,team))
            rows=c.fetchall(); c.close(); conn.close(); return [{'supervisor_id':r[0],'expo_push_token':r[1]} for r in rows]
        except Exception as e: print(f'Error getting attendance request recipients: {e}'); return []

    def supervisor_attendance_requests(self, supervisor_id, status='pending'):
        try:
            conn=self._connect(); c=conn.cursor(); params=[supervisor_id,supervisor_id]
            status_clause=''
            if status in {'pending','approved','rejected'}: status_clause=' AND ar.status=%s'; params.append(status)
            c.execute(f'''SELECT ar.id,ar.action,ar.requested_at,ar.reason,ar.status,ar.reviewer_name,
                ar.decision_reason,ar.decided_at,ar.created_at,w.worker_number,w.name,w.team
                FROM attendance_requests ar JOIN workers w ON w.worker_number=ar.worker_number
                WHERE (EXISTS(SELECT 1 FROM supervisor_worker_assignments wa WHERE wa.supervisor_id=%s AND wa.worker_number=w.worker_number)
                  OR EXISTS(SELECT 1 FROM supervisor_team_assignments ta WHERE ta.supervisor_id=%s AND ta.team=w.team))
                {status_clause} ORDER BY ar.created_at DESC''',tuple(params)); rows=c.fetchall(); c.close(); conn.close()
            return [{**self._attendance_request_from_row(r[:9]),'worker_number':r[9],'worker_name':r[10],'worker_team':r[11]} for r in rows]
        except Exception as e: print(f'Error listing supervisor attendance requests: {e}'); return []

    def decide_attendance_request(self, supervisor, request_id, decision, decision_reason=None):
        if decision not in {'approved','rejected'}: return False,'Choose approve or reject'
        decision_reason=str(decision_reason or '').strip()
        if decision=='rejected' and not decision_reason: return False,'A rejection reason is required'
        conn=None
        try:
            conn=self._connect(); c=conn.cursor(); conn.start_transaction()
            c.execute('''SELECT ar.worker_number,ar.action,ar.requested_at,ar.reason,ar.status,w.team
                FROM attendance_requests ar JOIN workers w ON w.worker_number=ar.worker_number
                WHERE ar.id=%s FOR UPDATE''',(request_id,)); row=c.fetchone()
            if not row or row[4]!='pending': conn.rollback(); c.close(); conn.close(); return False,'Request is no longer pending'
            c.execute('''SELECT 1 WHERE EXISTS(SELECT 1 FROM supervisor_worker_assignments WHERE supervisor_id=%s AND worker_number=%s)
                OR EXISTS(SELECT 1 FROM supervisor_team_assignments WHERE supervisor_id=%s AND team=%s)''',
                (supervisor['id'],row[0],supervisor['id'],row[5]))
            if not c.fetchone(): conn.rollback(); c.close(); conn.close(); return False,'This worker is not assigned to you'
            attendance_id=None
            if decision=='approved':
                requested_at=row[2]; attendance_date=requested_at.date()
                c.execute('SELECT id,check_in_at,check_out_at FROM attendance_records WHERE worker_number=%s AND attendance_date=%s FOR UPDATE',(row[0],attendance_date)); attendance=c.fetchone()
                if row[1]=='check_in':
                    if attendance: conn.rollback(); c.close(); conn.close(); return False,'Attendance already has a check-in for this date'
                    c.execute('''INSERT INTO attendance_records(worker_number,attendance_date,check_in_at,recorded_by,check_in_reason)
                        VALUES(%s,%s,%s,%s,%s)''',(row[0],attendance_date,requested_at,supervisor['display_name'],row[3])); attendance_id=c.lastrowid
                else:
                    if not attendance: conn.rollback(); c.close(); conn.close(); return False,'A check-in must be recorded before approving check-out'
                    if attendance[2]: conn.rollback(); c.close(); conn.close(); return False,'Attendance already has a check-out for this date'
                    if requested_at<attendance[1]: conn.rollback(); c.close(); conn.close(); return False,'Requested check-out is before check-in'
                    attendance_id=attendance[0]; c.execute('''UPDATE attendance_records SET check_out_at=%s,
                        recorded_by=%s,check_out_reason=%s WHERE id=%s''',(requested_at,supervisor['display_name'],row[3],attendance_id))
            c.execute('''UPDATE attendance_requests SET status=%s,reviewed_by=%s,reviewer_name=%s,
                decision_reason=%s,decided_at=CURRENT_TIMESTAMP,attendance_record_id=%s WHERE id=%s''',
                (decision,supervisor['id'],supervisor['display_name'],decision_reason or None,attendance_id,request_id))
            conn.commit(); c.close(); conn.close(); return True,'Attendance request '+decision
        except Exception as e:
            if conn:
                try: conn.rollback(); conn.close()
                except Exception: pass
            print(f'Error deciding attendance request: {e}'); return False,str(e)

    def submit_worker_proof(self, worker_number, instance_id, comment, proof_path):
        try:
            conn=self._connect(); c=conn.cursor(); c.execute('''SELECT review_status FROM instances
                WHERE instance_id=%s AND worker_number=%s AND identity_status='confirmed' ''',
                (instance_id,worker_number)); row=c.fetchone()
            if not row or row[0] != 'pending': c.close(); conn.close(); return False,'This alert cannot accept a worker submission'
            c.execute('''INSERT INTO worker_proof_submissions
                (instance_id,worker_number,comment,proof_path)
                VALUES(%s,%s,%s,%s)''',(instance_id,worker_number,comment,proof_path))
            c.execute('''UPDATE instances SET review_status='worker_submitted',
                worker_acknowledged_at=CURRENT_TIMESTAMP, worker_comment=%s,
                worker_proof_path=%s, worker_proof_at=CURRENT_TIMESTAMP,
                review_reason=NULL, reviewed_by=NULL, review_updated_at=NULL
                WHERE instance_id=%s''',(comment,proof_path,instance_id))
            c.execute('''INSERT INTO violation_review_events(instance_id,previous_status,review_status,review_reason,reviewer_name) VALUES(%s,'pending','worker_submitted',%s,%s)''',(instance_id,comment,worker_number)); conn.commit(); c.close(); conn.close(); return True,'Proof submitted for supervisor review'
        except Exception as e: print(f'Error submitting worker proof: {e}'); return False,str(e)

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
                1 if worker.get('is_active', True) else 0
                , password_hash
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

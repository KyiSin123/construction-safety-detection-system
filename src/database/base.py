"""Shared connection config, schema setup, and formatting helpers used by every domain mixin."""

import os
from datetime import datetime

import mysql.connector


INSTANCE_IDENTITY_COLUMNS = {
    'detection_batch_id': 'VARCHAR(64) NULL',
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


class BaseDatabase:
    """Connection handling and schema migrations shared by all Database mixins."""

    def __init__(self):
        self.config = {
            'host': os.getenv('MYSQL_HOST', 'localhost'),
            'port': int(os.getenv('MYSQL_PORT', '3306')),
            'user': os.getenv('MYSQL_USER', 'root'),
            'password': os.getenv('MYSQL_PASSWORD', ''),
            'database': os.getenv('MYSQL_DATABASE', 'helmet_detection'),
        }
        # Aiven (and most managed MySQL hosts) require an encrypted connection. Pointing
        # MYSQL_SSL_CA at the downloaded CA certificate verifies the server; leaving it unset
        # still connects over TLS, just without verifying the certificate chain.
        ssl_ca = os.getenv('MYSQL_SSL_CA')
        if ssl_ca:
            self.config['ssl_ca'] = ssl_ca
            self.config['ssl_verify_cert'] = True

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
                CREATE TABLE IF NOT EXISTS unknown_alert_daily_batches (
                    alert_date DATE PRIMARY KEY,
                    detection_batch_id VARCHAR(64) NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY unique_unknown_alert_batch (detection_batch_id)
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
            c.execute('''CREATE TABLE IF NOT EXISTS worker_proof_submissions (
                id INT AUTO_INCREMENT PRIMARY KEY, instance_id VARCHAR(255) NOT NULL,
                worker_number VARCHAR(64) NOT NULL, comment TEXT NOT NULL, proof_path TEXT NOT NULL,
                submitted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (instance_id) REFERENCES instances(instance_id) ON DELETE CASCADE,
                FOREIGN KEY (worker_number) REFERENCES workers(worker_number) ON DELETE CASCADE,
                INDEX worker_proof_instance (instance_id, submitted_at))''')

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
            cursor.execute("UPDATE instances SET review_status='resolved' WHERE review_status='ignored'")
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

    @staticmethod
    def _page_values(page, per_page):
        try: page = max(1, int(page or 1))
        except (TypeError, ValueError): page = 1
        try: per_page = min(50, max(1, int(per_page or 20)))
        except (TypeError, ValueError): per_page = 20
        return page, per_page

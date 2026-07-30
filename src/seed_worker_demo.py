"""Create or remove a deterministic worker account with representative mobile-app history."""

import argparse
import os
from datetime import datetime, timedelta

from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

from database import Database

WORKER_NUMBER = 'DEMO-WORKER'
PASSWORD = 'Demo1234'
INSTANCE_PREFIX = 'DEMO-WORKER-VIOLATION-'


def seed(db):
    conn = db._connect()
    c = conn.cursor()
    now = datetime.now().replace(microsecond=0)
    c.execute('''
        INSERT INTO workers (worker_number, name, team, password_hash, is_active, phone, email)
        VALUES (%s, %s, %s, %s, 1, %s, %s)
        ON DUPLICATE KEY UPDATE name = VALUES(name), team = VALUES(team),
            password_hash = VALUES(password_hash), is_active = 1, phone = VALUES(phone), email = VALUES(email)
    ''', (
        WORKER_NUMBER, 'Demo Worker', 'Demo Team', generate_password_hash(PASSWORD),
        '+95 9 123 456 789', 'demo.worker@example.com',
    ))

    c.execute("SELECT id FROM supervisors WHERE is_active=1 ORDER BY role='admin' DESC, id LIMIT 1")
    supervisor = c.fetchone()
    if supervisor:
        c.execute(
            'INSERT IGNORE INTO supervisor_worker_assignments (supervisor_id, worker_number) VALUES (%s, %s)',
            (supervisor[0], WORKER_NUMBER),
        )

    records = [
        (1, 'helmet', 'pending'),
        (3, 'vest', 'worker_submitted'),
        (8, 'mask', 'resolved'),
        (15, 'helmet,vest', 'ignored'),
    ]
    for index, (days, ppe, status) in enumerate(records, 1):
        detected = now - timedelta(days=days)
        resolved = status in {'resolved', 'ignored'}
        c.execute('''
            INSERT INTO instances (
                instance_id, first_detected, last_updated, is_compliant, missing_ppe,
                detected_ppe, worker_number, worker_name, worker_team, identity_confidence, identity_status,
                identity_source, review_status, review_reason, reviewed_by, review_updated_at
            )
            VALUES (%s, %s, %s, 0, %s, 'person', %s, 'Demo Worker', 'Demo Team', .98, 'confirmed', 'demo_seed', %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE first_detected = VALUES(first_detected), last_updated = VALUES(last_updated),
                missing_ppe = VALUES(missing_ppe), worker_number = VALUES(worker_number), worker_name = VALUES(worker_name),
                worker_team = VALUES(worker_team), identity_status = 'confirmed', review_status = VALUES(review_status),
                review_reason = VALUES(review_reason), reviewed_by = VALUES(reviewed_by), review_updated_at = VALUES(review_updated_at)
        ''', (
            f'{INSTANCE_PREFIX}{index:03d}', detected, detected, ppe, WORKER_NUMBER, status,
            'Demo supervisor review' if resolved else None,
            'Demo Supervisor' if resolved else None,
            detected if resolved else None,
        ))

    for days in (1, 2, 3, 5, 8):
        day = (now - timedelta(days=days)).date()
        check_in = datetime.combine(day, datetime.min.time()).replace(hour=8)
        check_out = check_in + timedelta(hours=9)
        c.execute('''
            INSERT INTO attendance_records (worker_number, attendance_date, check_in_at, check_out_at, recorded_by)
            VALUES (%s, %s, %s, %s, 'ID detection')
            ON DUPLICATE KEY UPDATE check_in_at = VALUES(check_in_at), check_out_at = VALUES(check_out_at),
                recorded_by = VALUES(recorded_by)
        ''', (WORKER_NUMBER, day, check_in, check_out))

    c.execute('DELETE FROM attendance_requests WHERE worker_number = %s', (WORKER_NUMBER,))
    request_rows = [
        ('check_in', now - timedelta(days=4, hours=8), 'ID badge was obscured', 'pending', None, None, None),
        ('check_out', now - timedelta(days=6, hours=-1), 'Camera did not read my badge', 'approved',
         supervisor[0] if supervisor else None, 'Demo Supervisor', None),
        ('check_in', now - timedelta(days=10, hours=8), 'Badge reflection prevented detection', 'rejected',
         supervisor[0] if supervisor else None, 'Demo Supervisor', 'Site log did not confirm arrival'),
    ]
    for action, requested, reason, status, reviewed_by, reviewer_name, decision_reason in request_rows:
        c.execute('''
            INSERT INTO attendance_requests (worker_number, action, requested_at, reason, status,
                reviewed_by, reviewer_name, decision_reason, decided_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (
            WORKER_NUMBER, action, requested, reason, status,
            reviewed_by, reviewer_name, decision_reason, now if status != 'pending' else None,
        ))

    conn.commit()
    c.close()
    conn.close()


def cleanup(db):
    conn = db._connect()
    c = conn.cursor()
    c.execute('DELETE FROM attendance_requests WHERE worker_number = %s', (WORKER_NUMBER,))
    c.execute('DELETE FROM attendance_records WHERE worker_number = %s', (WORKER_NUMBER,))
    c.execute('DELETE FROM instances WHERE instance_id LIKE %s', (f'{INSTANCE_PREFIX}%',))
    c.execute('DELETE FROM workers WHERE worker_number = %s', (WORKER_NUMBER,))
    conn.commit()
    c.close()
    conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cleanup', action='store_true')
    args = parser.parse_args()

    load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))
    db = Database()
    db.init_db()

    if args.cleanup:
        cleanup(db)
        print('Removed the demo worker and demo-owned history.')
    else:
        seed(db)
        print(f'Demo worker ready: {WORKER_NUMBER} / {PASSWORD}')


if __name__ == '__main__':
    main()

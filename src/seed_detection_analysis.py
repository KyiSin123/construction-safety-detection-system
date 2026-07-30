"""Create or remove deterministic demo records for the admin analytics charts."""

import argparse
import os
from datetime import datetime, timedelta

from dotenv import load_dotenv

from database import Database


SEED_PREFIX = 'DEMO-ANALYTICS-'
DEMO_RECORDS = (
    (0, 'helmet', 'pending'),
    (0, 'helmet,vest', 'worker_submitted'),
    (1, 'vest', 'resolved'),
    (2, 'mask', 'resolved'),
    (3, 'helmet,mask', 'pending'),
    (4, 'boots', 'resolved'),
    (6, 'helmet', 'worker_submitted'),
    (8, 'vest,gloves', 'pending'),
    (12, 'helmet', 'resolved'),
    (20, 'mask,vest', 'resolved'),
    (29, 'gloves', 'pending'),
    (31, 'helmet,boots', 'resolved'),
    (45, 'vest', 'worker_submitted'),
    (60, 'helmet,mask,vest', 'pending'),
    (89, 'boots', 'resolved'),
    (91, 'helmet', 'resolved'),
)


def seed(db):
    conn = db._connect()
    cursor = conn.cursor()
    now = datetime.now().replace(microsecond=0)

    demo_hours = (7, 8, 8, 9, 9, 9, 10, 12, 13, 15, 15, 17, 18, 18, 20, 22)
    for index, (days_ago, missing_ppe, review_status) in enumerate(DEMO_RECORDS, start=1):
        detected_at = (now - timedelta(days=days_ago)).replace(
            hour=demo_hours[index - 1],
            minute=(index * 7) % 60,
        )
        instance_id = f'{SEED_PREFIX}{index:03d}'
        cursor.execute(
            '''
            INSERT INTO instances (
                instance_id, first_detected, last_updated, is_compliant,
                missing_ppe, detected_ppe, worker_number, worker_name,
                worker_team, identity_confidence, identity_status,
                identity_source, review_status, review_reason, reviewed_by,
                review_updated_at
            )
            VALUES (%s, %s, %s, 0, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                first_detected = VALUES(first_detected),
                last_updated = VALUES(last_updated),
                is_compliant = VALUES(is_compliant),
                missing_ppe = VALUES(missing_ppe),
                detected_ppe = VALUES(detected_ppe),
                worker_number = VALUES(worker_number),
                worker_name = VALUES(worker_name),
                worker_team = VALUES(worker_team),
                identity_confidence = VALUES(identity_confidence),
                identity_status = VALUES(identity_status),
                identity_source = VALUES(identity_source),
                review_status = VALUES(review_status),
                review_reason = VALUES(review_reason),
                reviewed_by = VALUES(reviewed_by),
                review_updated_at = VALUES(review_updated_at)
            ''',
            (
                instance_id,
                detected_at,
                detected_at,
                missing_ppe,
                'person',
                f'DEMO-{index:03d}',
                f'Demo Worker {index:02d}',
                ('Concrete', 'Electrical', 'Scaffolding')[index % 3],
                0.91,
                'confirmed',
                'demo_seed',
                review_status,
                'Generated for dashboard testing',
                'Demo Administrator',
                detected_at if review_status == 'resolved' else None,
            ),
        )

    conn.commit()
    cursor.close()
    conn.close()
    return len(DEMO_RECORDS)


def cleanup(db):
    conn = db._connect()
    cursor = conn.cursor()
    cursor.execute(
        'DELETE FROM snapshots WHERE instance_id LIKE %s',
        (f'{SEED_PREFIX}%',),
    )
    cursor.execute(
        'DELETE FROM instances WHERE instance_id LIKE %s',
        (f'{SEED_PREFIX}%',),
    )
    deleted = cursor.rowcount
    conn.commit()
    cursor.close()
    conn.close()
    return deleted


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--cleanup',
        action='store_true',
        help='Remove only records created by this script.',
    )
    args = parser.parse_args()

    load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))
    db = Database()
    db.init_db()

    if args.cleanup:
        print(f'Removed {cleanup(db)} demo detection records.')
    else:
        print(f'Created or refreshed {seed(db)} demo detection records.')
        for days in (7, 30, 90):
            analysis = db.get_detection_analysis(days)
            total = analysis['total_violations'] if analysis else 'unavailable'
            print(f'Last {days} days: {total} total detections.')


if __name__ == '__main__':
    main()

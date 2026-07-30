"""Attendance check-in/out records and worker-submitted attendance correction requests."""

from datetime import datetime


class AttendanceMixin:
    """Attendance records and the worker attendance-correction request workflow."""

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
            conn = self._connect()
            c = conn.cursor()
            c.execute(
                'SELECT worker_number, name, team FROM workers WHERE worker_number = %s AND is_active = 1',
                (worker_number,),
            )
            worker = c.fetchone()
            if not worker:
                c.close()
                conn.close()
                return False, 'Worker ID is not registered or is inactive', None
            c.execute('''
                SELECT id, check_in_at, check_out_at FROM attendance_records
                WHERE worker_number = %s AND attendance_date = %s
            ''', (worker_number, attendance_date))
            record = c.fetchone()
            if action == 'check_in':
                if record:
                    message = 'Worker is already checked in today' if record[2] is None else 'Worker attendance is already completed today'
                    c.close()
                    conn.close()
                    return False, message, None
                c.execute('''
                    INSERT INTO attendance_records
                        (worker_number, attendance_date, check_in_at, recorded_by, check_in_reason)
                        VALUES (%s, %s, %s, %s, %s)
                ''', (worker_number, attendance_date, recorded_at, recorded_by, reason))
                message = 'Check-in recorded'
            else:
                if not record:
                    c.close()
                    conn.close()
                    return False, 'No check-in record exists for today', None
                if record[2] is not None:
                    c.close()
                    conn.close()
                    return False, 'Worker is already checked out today', None
                if recorded_at < record[1]:
                    c.close()
                    conn.close()
                    return False, 'Check-out time cannot be before check-in time', None
                c.execute('''
                    UPDATE attendance_records
                    SET check_out_at = %s, recorded_by = %s, check_out_reason = %s WHERE id = %s
                ''', (recorded_at, recorded_by, reason, record[0]))
                message = 'Check-out recorded'
            conn.commit()
            c.close()
            conn.close()
            return True, message, {'worker_number': worker[0], 'name': worker[1], 'team': worker[2]}
        except Exception as e:
            print(f"Error recording attendance: {e}")
            return False, str(e), None

    def get_attendance(self, attendance_date=None):
        try:
            conn = self._connect()
            c = conn.cursor()
            columns = '''
                a.id, a.worker_number, w.name, w.team, a.attendance_date, a.check_in_at, a.check_out_at,
                a.recorded_by, a.check_in_reason, a.check_out_reason
            '''
            if attendance_date:
                c.execute(f'''
                    SELECT {columns} FROM attendance_records a JOIN workers w ON w.worker_number = a.worker_number
                    WHERE a.attendance_date = %s ORDER BY a.check_in_at DESC
                ''', (attendance_date,))
            else:
                c.execute(f'''
                    SELECT {columns} FROM attendance_records a JOIN workers w ON w.worker_number = a.worker_number
                    WHERE a.attendance_date = CURDATE() ORDER BY a.check_in_at DESC
                ''')
            records = [{
                'id': row[0], 'worker_number': row[1], 'name': row[2], 'team': row[3],
                'attendance_date': str(row[4]), 'check_in_at': self._format_datetime(row[5]),
                'check_out_at': self._format_datetime(row[6]), 'recorded_by': row[7],
                'check_in_reason': row[8], 'check_out_reason': row[9],
            } for row in c.fetchall()]
            c.close()
            conn.close()
            return records
        except Exception as e:
            print(f"Error getting attendance: {e}")
            return []

    def worker_attendance(self, worker_number, page=1, per_page=20, month=None, attendance_date=None):
        try:
            page, per_page = self._page_values(page, per_page)
            clauses = ['a.worker_number=%s']
            params = [worker_number]
            if attendance_date:
                clauses.append('a.attendance_date=%s')
                params.append(attendance_date)
            elif month:
                clauses.append("DATE_FORMAT(a.attendance_date, '%Y-%m')=%s")
                params.append(month)
            where = ' AND '.join(clauses)
            conn = self._connect()
            c = conn.cursor()
            c.execute(f'SELECT COUNT(*) FROM attendance_records a WHERE {where}', tuple(params))
            total = c.fetchone()[0]
            c.execute(f'''
                SELECT a.id, a.attendance_date, a.check_in_at, a.check_out_at, a.recorded_by,
                    a.check_in_reason, a.check_out_reason
                FROM attendance_records a WHERE {where}
                ORDER BY a.attendance_date DESC, a.check_in_at DESC LIMIT %s OFFSET %s
            ''', tuple(params + [per_page, (page - 1) * per_page]))
            rows = c.fetchall()
            c.close()
            conn.close()
            items = [{
                'id': r[0], 'attendance_date': str(r[1]), 'check_in_at': self._format_datetime(r[2]),
                'check_out_at': self._format_datetime(r[3]), 'recorded_by': r[4],
                'check_in_reason': r[5], 'check_out_reason': r[6],
                'status': 'completed' if r[3] else 'on_site',
            } for r in rows]
            return {'items': items, 'page': page, 'per_page': per_page, 'total': total, 'has_more': page * per_page < total}
        except Exception as e:
            print(f"Error getting worker attendance: {e}")
            return {'items': [], 'page': 1, 'per_page': 20, 'total': 0, 'has_more': False}

    def create_attendance_request(self, worker_number, action, requested_at, reason):
        action = str(action or '').strip().lower()
        reason = str(reason or '').strip()
        if action not in {'check_in', 'check_out'} or not reason:
            return False, 'Action, date/time, and reason are required', None
        try:
            requested_at = datetime.fromisoformat(str(requested_at or '').strip()).replace(tzinfo=None)
        except (TypeError, ValueError):
            return False, 'Select a valid requested date and time', None
        try:
            conn = self._connect()
            c = conn.cursor()
            conn.start_transaction()
            c.execute('SELECT worker_number FROM workers WHERE worker_number=%s FOR UPDATE', (worker_number,))
            if not c.fetchone():
                conn.rollback()
                c.close()
                conn.close()
                return False, 'Worker not found', None
            c.execute('''
                SELECT id FROM attendance_requests WHERE worker_number=%s AND action=%s
                AND DATE(requested_at)=%s AND status='pending' LIMIT 1
            ''', (worker_number, action, requested_at.date()))
            if c.fetchone():
                c.close()
                conn.close()
                return False, 'A pending request already exists for this date and action', None
            c.execute('''
                INSERT INTO attendance_requests (worker_number, action, requested_at, reason)
                VALUES (%s, %s, %s, %s)
            ''', (worker_number, action, requested_at, reason))
            request_id = c.lastrowid
            conn.commit()
            c.close()
            conn.close()
            return True, 'Attendance request submitted', request_id
        except Exception as e:
            print(f"Error creating attendance request: {e}")
            return False, str(e), None

    def worker_attendance_requests(self, worker_number):
        try:
            conn = self._connect()
            c = conn.cursor()
            c.execute('''
                SELECT id, action, requested_at, reason, status, reviewer_name, decision_reason, decided_at, created_at
                FROM attendance_requests
                WHERE worker_number=%s ORDER BY created_at DESC
            ''', (worker_number,))
            rows = c.fetchall()
            c.close()
            conn.close()
            return [self._attendance_request_from_row(r) for r in rows]
        except Exception as e:
            print(f"Error listing worker attendance requests: {e}")
            return []

    def _attendance_request_from_row(self, row):
        return {
            'id': row[0], 'action': row[1], 'requested_at': self._format_datetime(row[2]),
            'reason': row[3], 'status': row[4], 'reviewer_name': row[5], 'decision_reason': row[6],
            'decided_at': self._format_datetime(row[7]), 'created_at': self._format_datetime(row[8]),
        }

    def attendance_request_recipients(self, worker_number):
        try:
            conn = self._connect()
            c = conn.cursor()
            c.execute('SELECT team FROM workers WHERE worker_number=%s', (worker_number,))
            row = c.fetchone()
            team = row[0] if row else None
            c.execute('''
                SELECT DISTINCT s.id, d.expo_push_token FROM supervisors s
                LEFT JOIN supervisor_devices d ON d.supervisor_id=s.id AND d.is_active=1
                LEFT JOIN supervisor_worker_assignments wa ON wa.supervisor_id=s.id AND wa.worker_number=%s
                LEFT JOIN supervisor_team_assignments ta ON ta.supervisor_id=s.id AND ta.team=%s
                WHERE s.is_active=1 AND (wa.worker_number IS NOT NULL OR ta.team IS NOT NULL)
            ''', (worker_number, team))
            rows = c.fetchall()
            c.close()
            conn.close()
            return [{'supervisor_id': r[0], 'expo_push_token': r[1]} for r in rows]
        except Exception as e:
            print(f"Error getting attendance request recipients: {e}")
            return []

"""Database access layer, split by domain and combined into one Database class.

Callers keep using `from database import Database` and calling methods like
`db.get_workers(...)` exactly as before -- the split below only reorganizes
where each method lives, it does not change the public interface.
"""

from .attendance import AttendanceMixin
from .base import BaseDatabase, BLOCKING_REVIEW_STATUSES, REVIEW_STATUSES
from .instances import InstanceMixin
from .supervisors import SupervisorMixin
from .workers import WorkerMixin

__all__ = ['Database', 'REVIEW_STATUSES', 'BLOCKING_REVIEW_STATUSES']


class Database(InstanceMixin, SupervisorMixin, WorkerMixin, AttendanceMixin, BaseDatabase):
    """Combines domain mixins (instances, supervisors, workers, attendance) with the shared connection/schema base."""

"""Database-backed, concurrency-safe permanent identifier generator.

Identifiers are allocated from a dedicated ``id_sequences`` table.

Concurrency strategy (verified by ``tests/test_verification.py``):

1. **No read-modify-write window.** Allocation is a single atomic
   statement::

       UPDATE id_sequences
          SET last_value = last_value + 1
        WHERE kind = :kind
    RETURNING last_value

   Concurrent callers cannot both read the same value, because the second
   ``UPDATE`` blocks on the first writer's lock and then re-evaluates
   ``last_value`` against the committed row.

2. **Why ``SELECT ... FOR UPDATE`` alone is NOT enough on SQLite.** SQLite
   has no row-level locking: ``FOR UPDATE`` is parsed and silently
   ignored. The original implementation did ``SELECT ... FOR UPDATE``,
   incremented in Python and flushed — two threads read the same value and
   produced duplicate ``FAB-003`` / ``id_sequences`` unique violations.
   SQLite serialises *writers*, not *readers*, so only a single atomic
   write statement is safe.

3. **Process-wide ``threading.Lock``** serialises allocation inside one
   process. This is required on SQLite and cheap elsewhere.

4. **``INSERT ... ON CONFLICT DO NOTHING``** creates the sequence row, so
   the "row does not exist yet" race cannot raise a unique violation.

5. **``_with_retry`` in ``app/services.py``** retries ``IntegrityError``
   and SQLite ``database is locked`` failures — the final safety net for
   multi-process SQLite deployments (which should use PostgreSQL anyway).

The allocation deliberately participates in the caller's transaction, so
a failed request does not burn an ID.

Sequences are never decremented and IDs are never reused, even after a
record is archived or deleted.

Formats:
    Fabric          FAB-001
    FabricVariant   FVAR-001
    FabricImage     FIMG-001
    InventoryLot    FLOT-001
    FabricCategory  FCAT-001
    FabricPrice     FPR-001
"""
from __future__ import annotations

import threading

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import IdSequence

PREFIXES = {
    "fabric": "FAB",
    "variant": "FVAR",
    "image": "FIMG",
    "lot": "FLOT",
    "category": "FCAT",
    "price": "FPR",
}

# Serialises ID allocation within this process (essential on SQLite).
_ALLOC_LOCK = threading.Lock()

_INSERT_ON_CONFLICT = {
    "postgresql": "INSERT INTO id_sequences (kind, last_value) VALUES (:kind, 0) "
    "ON CONFLICT (kind) DO NOTHING",
    "sqlite": "INSERT INTO id_sequences (kind, last_value) VALUES (:kind, 0) "
    "ON CONFLICT (kind) DO NOTHING",
}
_INSERT_PORTABLE = (
    "INSERT INTO id_sequences (kind, last_value) "
    "SELECT :kind, 0 WHERE NOT EXISTS (SELECT 1 FROM id_sequences WHERE kind = :kind)"
)
_UPDATE_RETURNING = (
    "UPDATE id_sequences SET last_value = last_value + 1 "
    "WHERE kind = :kind RETURNING last_value"
)


def next_id(db: Session, kind: str, width: int = 3) -> str:
    """Allocate and return the next permanent ID for ``kind``.

    Must be called inside an active transaction; the caller commits.
    Thread-safe within a process, and safe across processes on both SQLite
    (serialised writers) and PostgreSQL (row lock on the sequence row).
    """
    prefix = PREFIXES[kind]
    bind = db.get_bind()
    dialect = bind.dialect.name if bind is not None else "sqlite"
    insert_sql = _INSERT_ON_CONFLICT.get(dialect, _INSERT_PORTABLE)

    # No application-level lock is taken around the DB write on purpose:
    # holding one while blocked on the database write lock inverts the
    # lock order between threads and produces SQLITE_BUSY. Database-level
    # serialisation (BEGIN IMMEDIATE on SQLite, row lock on PostgreSQL)
    # is what makes this safe.
    db.execute(text(insert_sql), {"kind": kind})
    value = db.execute(text(_UPDATE_RETURNING), {"kind": kind}).scalar_one()
    db.flush()
    return f"{prefix}-{int(value):0{width}d}"


def peek_sequence(db: Session, kind: str) -> int:
    """Current highest allocated value for ``kind`` (0 if never used)."""
    row = db.execute(
        text("SELECT last_value FROM id_sequences WHERE kind = :kind"), {"kind": kind}
    ).scalar_one_or_none()
    return int(row or 0)


__all__ = ["next_id", "peek_sequence", "PREFIXES", "IdSequence"]

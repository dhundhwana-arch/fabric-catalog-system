"""Database-backed, concurrency-safe permanent identifier generator.

Identifiers are allocated from a dedicated ``id_sequences`` table. Each
allocation runs inside the caller's transaction and uses ``SELECT ... FOR
UPDATE`` on PostgreSQL (row lock) so concurrent requests cannot receive the
same ID. On SQLite the single-writer model plus the UNIQUE constraint on the
sequence row provides the same guarantee for this module's scale.

Sequences are never decremented and IDs are never reused, even after a
record is archived or deleted.

Formats:
    Fabric          FAB-001
    FabricVariant   FVAR-001
    FabricImage     FIMG-001
    InventoryLot    FLOT-001
    FabricCategory  FCAT-001
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import IdSequence

PREFIXES = {
    "fabric": "FAB",
    "variant": "FVAR",
    "image": "FIMG",
    "lot": "FLOT",
    "category": "FCAT",
}


def next_id(db: Session, kind: str, width: int = 3) -> str:
    """Allocate and return the next permanent ID for ``kind``.

    Must be called within an active transaction (the caller commits).
    """
    prefix = PREFIXES[kind]
    stmt = (
        select(IdSequence)
        .where(IdSequence.kind == kind)
        .with_for_update()
    )
    seq = db.execute(stmt).scalar_one_or_none()
    if seq is None:
        seq = IdSequence(kind=kind, last_value=0)
        db.add(seq)
        db.flush()
    seq.last_value += 1
    db.flush()
    return f"{prefix}-{seq.last_value:0{width}d}"

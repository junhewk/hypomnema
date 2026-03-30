"""SQLite transaction helpers for contended WAL workloads."""

from __future__ import annotations

import asyncio
import sqlite3
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


SQLITE_BUSY_TIMEOUT_MS = 15_000


@dataclass
class _WriteGate:
    """Per-database write gate used to serialize SQLite writers."""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    owner_task: asyncio.Task[object] | None = None
    depth: int = 0
    connection_ids: set[int] = field(default_factory=set)


_WRITE_GATES: dict[tuple[int, str], _WriteGate] = {}


class SQLiteConnectionLike(Protocol):
    """Minimal connection protocol shared by aiosqlite and sync adapters."""

    async def execute(
        self,
        sql: str,
        parameters: tuple[object, ...] | list[object] | None = None,
    ) -> object: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


def _db_key(db: SQLiteConnectionLike) -> str:
    configured = getattr(db, "_hypomnema_db_key", None)
    if configured:
        return str(configured)
    return f"connection:{id(db)}"


async def _acquire_write_gate(db: SQLiteConnectionLike) -> _WriteGate:
    gate_key = (id(asyncio.get_running_loop()), _db_key(db))
    gate = _WRITE_GATES.setdefault(gate_key, _WriteGate())
    current_task = asyncio.current_task()
    if current_task is None:
        raise RuntimeError("SQLite write transactions require a running asyncio task")

    connection_id = id(db)
    if gate.owner_task is current_task:
        if gate.connection_ids and connection_id not in gate.connection_ids:
            raise RuntimeError(
                "Nested SQLite write transactions across different connections "
                "for the same database are not supported",
            )
        gate.depth += 1
        gate.connection_ids.add(connection_id)
        return gate

    await gate.lock.acquire()
    gate.owner_task = current_task
    gate.depth = 1
    gate.connection_ids = {connection_id}
    return gate


def _release_write_gate(gate: _WriteGate) -> None:
    current_task = asyncio.current_task()
    if current_task is None or gate.owner_task is not current_task:
        return

    gate.depth -= 1
    if gate.depth > 0:
        return

    gate.owner_task = None
    gate.connection_ids.clear()
    gate.lock.release()


@asynccontextmanager
async def immediate_transaction(db: SQLiteConnectionLike) -> AsyncGenerator[None, None]:
    """Run a block inside a serialized ``BEGIN IMMEDIATE`` transaction."""
    gate = await _acquire_write_gate(db)
    owns_transaction = False
    try:
        await db.execute("BEGIN IMMEDIATE")
        owns_transaction = True
    except sqlite3.OperationalError as exc:
        if "cannot start a transaction within a transaction" not in str(exc).lower():
            raise

    try:
        yield
    except Exception:
        if owns_transaction:
            await db.rollback()
        raise
    else:
        if owns_transaction:
            await db.commit()
    finally:
        _release_write_gate(gate)

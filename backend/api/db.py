"""Connexion PostgreSQL (asyncpg) et application du schéma."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import asyncpg

logger = logging.getLogger("tenderpulse.db")
SCHEMA_PATH = Path(__file__).with_name("init.sql")


async def _init_connection(conn: asyncpg.Connection) -> None:
    for pg_type in ("json", "jsonb"):
        await conn.set_type_codec(pg_type, encoder=lambda v: json.dumps(v, ensure_ascii=False), decoder=json.loads,
                                  schema="pg_catalog")


async def create_pool(database_url: str, *, attempts: int = 30, delay_s: float = 2.0) -> asyncpg.Pool:
    """Ouvre le pool en patientant tant que PostgreSQL démarre."""
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await asyncpg.create_pool(database_url, min_size=1, max_size=10, init=_init_connection)
        except (OSError, asyncpg.PostgresError) as exc:
            last_error = exc
            logger.warning("PostgreSQL indisponible (tentative %d/%d) : %s", attempt, attempts, exc)
            await asyncio.sleep(delay_s)
    raise RuntimeError(f"Connexion à PostgreSQL impossible : {last_error}")


async def apply_schema(pool: asyncpg.Pool) -> None:
    """Applique `init.sql` (idempotent) pour garantir un schéma à jour au démarrage."""
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))

from __future__ import annotations

import os
from pathlib import Path

from alembic import context
from dotenv import dotenv_values
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

ROOT_DIR = Path(__file__).resolve().parents[1]


def _load_env_defaults() -> None:
    merged: dict[str, str] = {}
    for filename in (".env", ".env.local"):
        env_path = ROOT_DIR / filename
        if not env_path.exists():
            continue
        merged.update(
            {
                key: value
                for key, value in dotenv_values(env_path).items()
                if value is not None
            }
        )
    for key, value in merged.items():
        os.environ.setdefault(key, value)


_load_env_defaults()

config = context.config
sql_dsn = os.getenv("SQL_DSN", "").strip()
if not sql_dsn:
    raise RuntimeError("SQL_DSN is required for Alembic migrations.")
config.set_main_option("sqlalchemy.url", sql_dsn)

target_metadata = None


def run_migrations_offline() -> None:
    context.configure(
        url=sql_dsn,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: object) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    import asyncio

    asyncio.run(run_migrations_online())

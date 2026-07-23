"""Helpers that provision migrated PostgreSQL test databases."""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy.engine import make_url

TEST_DB = "attest_test"
MIGRATION_TEST_DB = "attest_migration_test"
_DEFAULT_URL = "postgresql+asyncpg://attest:attest@localhost:5432/attest"


def repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "AGENTS.md").is_file():
            return parent
    msg = "repository root not found"
    raise RuntimeError(msg)


def base_url() -> str:
    return os.environ.get("DATABASE_URL", _DEFAULT_URL)


async def _recreate(db_name: str) -> None:
    admin_dsn = (
        make_url(base_url()).set(drivername="postgresql").render_as_string(hide_password=False)
    )
    connection = await asyncpg.connect(admin_dsn)
    try:
        await connection.execute(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)')
        await connection.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        await connection.close()


def provision_database(db_name: str) -> str:
    """Drop and recreate one empty test database; return its async URL."""
    try:
        asyncio.run(_recreate(db_name))
    except (OSError, asyncpg.PostgresError) as error:
        pytest.fail(
            f"PostgreSQL is required for integration tests; start it with `make infra-up` ({error})"
        )
    return make_url(base_url()).set(database=db_name).render_as_string(hide_password=False)


def alembic(arguments: list[str], database_url: str) -> subprocess.CompletedProcess[str]:
    """Run the real Alembic CLI against the given database."""
    command = [
        sys.executable,
        "-m",
        "alembic",
        "-c",
        str(repo_root() / "infra" / "migrations" / "alembic.ini"),
        *arguments,
    ]
    # Drop pytest-cov instrumentation variables: the subprocess would otherwise
    # record non-branch coverage data that cannot merge with the parent run's.
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("COV_CORE_", "COVERAGE_"))
    }
    environment["DATABASE_URL"] = database_url
    return subprocess.run(  # noqa: S603 - fixed command, test-only
        command,
        env=environment,
        cwd=repo_root(),
        capture_output=True,
        text=True,
        check=False,
    )


async def scalar(database_url: str, query: str) -> int:
    """Fetch one integer with a direct asyncpg connection."""
    dsn = make_url(database_url).set(drivername="postgresql").render_as_string(hide_password=False)
    connection = await asyncpg.connect(dsn)
    try:
        value = await connection.fetchval(query)
        assert isinstance(value, int)
        return value
    finally:
        await connection.close()

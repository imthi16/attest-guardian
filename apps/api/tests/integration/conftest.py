"""Fixtures for integration tests.

These require the local infrastructure from `make infra-up` (or the CI
service container); they fail fast with instructions otherwise.
"""

from collections.abc import AsyncIterator, Iterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from tests.integration.dbtools import TEST_DB, alembic, provision_database


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """One migrated database shared by repository and session tests."""
    url = provision_database(TEST_DB)
    result = alembic(["upgrade", "head"], url)
    assert result.returncode == 0, result.stderr
    yield url


@pytest.fixture
async def db_session(database_url: str) -> AsyncIterator[AsyncSession]:
    """A session inside an outer transaction that is always rolled back."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        factory = async_sessionmaker(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        async with factory() as session:
            yield session
        await transaction.rollback()
    await engine.dispose()

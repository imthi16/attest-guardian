"""Engine caching and transaction-scope behavior."""

import app.db.session as session_module
import pytest
from app.db.models import User
from app.db.session import (
    build_engine,
    build_session_factory,
    get_db_session,
    get_engine,
    get_session_factory,
    session_scope,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from tests.integration.factories import make_user, unique


def test_process_wide_engine_and_factory_are_cached() -> None:
    assert get_engine() is get_engine()
    assert get_session_factory() is get_session_factory()
    assert build_engine() is not build_engine()


async def test_session_scope_commits_on_success(database_url: str) -> None:
    engine = create_async_engine(database_url, poolclass=NullPool)
    factory = build_session_factory(engine)
    email = f"{unique('scope')}@example.test"

    async with session_scope(factory) as session:
        await make_user(session, email=email)

    async with factory() as check_session:
        found = await check_session.scalar(select(User).where(User.email == email))
        assert found is not None
    await engine.dispose()


async def test_session_scope_rolls_back_on_error(database_url: str) -> None:
    engine = create_async_engine(database_url, poolclass=NullPool)
    factory = build_session_factory(engine)
    email = f"{unique('rollback')}@example.test"

    with pytest.raises(RuntimeError, match="boom"):
        async with session_scope(factory) as session:
            await make_user(session, email=email)
            msg = "boom"
            raise RuntimeError(msg)

    async with factory() as check_session:
        found = await check_session.scalar(select(User).where(User.email == email))
        assert found is None
    await engine.dispose()


async def test_get_db_session_yields_transactional_session(
    monkeypatch: pytest.MonkeyPatch,
    database_url: str,
) -> None:
    engine = create_async_engine(database_url, poolclass=NullPool)
    factory = build_session_factory(engine)
    monkeypatch.setattr(session_module, "get_session_factory", lambda: factory)

    generator = get_db_session()
    session = await anext(generator)
    assert isinstance(session, AsyncSession)
    assert session.in_transaction()
    await generator.aclose()
    await engine.dispose()

import asyncio
from unittest.mock import AsyncMock, MagicMock
import uuid

from sqlalchemy.dialects import postgresql

from app.models.user import User
from app.services.auth import load_active_user_with_permissions


def test_loads_active_user_and_permissions_in_one_query():
    user = User(
        id=uuid.uuid4(),
        email="user@example.com",
        display_name="User",
        is_active=True,
    )
    unique_result = MagicMock()
    unique_result.scalar_one_or_none.return_value = user
    result = MagicMock()
    result.unique.return_value = unique_result
    db = AsyncMock()
    db.execute.return_value = result

    loaded = asyncio.run(load_active_user_with_permissions(db, user.id))

    assert loaded is user
    db.execute.assert_awaited_once()
    result.unique.assert_called_once_with()
    statement = db.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "user_groups" in sql
    assert "groups" in sql
    assert "bucket_permissions" in sql


def test_rejects_inactive_user():
    user = User(
        id=uuid.uuid4(),
        email="inactive@example.com",
        display_name="Inactive",
        is_active=False,
    )
    unique_result = MagicMock()
    unique_result.scalar_one_or_none.return_value = user
    result = MagicMock()
    result.unique.return_value = unique_result
    db = AsyncMock()
    db.execute.return_value = result

    loaded = asyncio.run(load_active_user_with_permissions(db, user.id))

    assert loaded is None
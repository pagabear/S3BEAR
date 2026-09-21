"""Unit tests for the pure logic in app.services.share.

These cover token generation/hashing and expiry parsing — the highest
bug-risk pure functions. DB-touching helpers are exercised via integration.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest

from app.models.share import ShareLink
from app.services import share


class TestGenerateToken:
    def test_returns_url_safe_string(self):
        token = share.generate_token()
        assert isinstance(token, str)
        assert token  # non-empty
        # url-safe base64 alphabet: letters, digits, - and _
        assert all(c.isalnum() or c in "-_" for c in token)

    def test_tokens_are_unique(self):
        tokens = {share.generate_token() for _ in range(1000)}
        assert len(tokens) == 1000

    def test_token_has_sufficient_entropy(self):
        # token_urlsafe(32) -> ~43 chars
        assert len(share.generate_token()) >= 40


class TestHashToken:
    def test_is_sha256_hex(self):
        h = share.hash_token("hello")
        assert h == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
        assert len(h) == 64

    def test_is_deterministic(self):
        assert share.hash_token("abc") == share.hash_token("abc")

    def test_differs_by_input(self):
        assert share.hash_token("abc") != share.hash_token("abd")


class TestParseExpiresIn:
    @pytest.mark.parametrize("value,delta_seconds", [
        ("1h", 3600),
        ("24h", 86400),
        ("7d", 604800),
        ("30d", 2592000),
    ])
    def test_shorthands(self, value, delta_seconds):
        before = datetime.now(timezone.utc)
        result = share.parse_expires_in(value)
        after = datetime.now(timezone.utc)
        assert result is not None
        assert result.tzinfo is not None  # timezone-aware
        expected_low = before.timestamp() + delta_seconds
        expected_high = after.timestamp() + delta_seconds
        assert expected_low <= result.timestamp() <= expected_high

    def test_none_means_never(self):
        assert share.parse_expires_in(None) is None

    def test_never_keyword_means_never(self):
        assert share.parse_expires_in("never") is None

    def test_empty_string_uses_default_7d(self):
        result = share.parse_expires_in("")
        assert result is not None
        # ~7 days out
        delta = result.timestamp() - datetime.now(timezone.utc).timestamp()
        assert 604800 - 5 <= delta <= 604800 + 5

    def test_integer_seconds(self):
        result = share.parse_expires_in(3600)
        assert result is not None
        delta = result.timestamp() - datetime.now(timezone.utc).timestamp()
        assert 3595 <= delta <= 3605

    def test_numeric_string_seconds(self):
        result = share.parse_expires_in("3600")
        assert result is not None
        delta = result.timestamp() - datetime.now(timezone.utc).timestamp()
        assert 3595 <= delta <= 3605

    def test_invalid_unit_raises(self):
        with pytest.raises(ValueError):
            share.parse_expires_in("5y")

    def test_negative_seconds_raises(self):
        with pytest.raises(ValueError):
            share.parse_expires_in(-100)

    def test_zero_raises(self):
        with pytest.raises(ValueError):
            share.parse_expires_in(0)


class TestResolveActiveLink:
    def test_validates_and_increments_a_shard_in_one_query(self, monkeypatch):
        db = AsyncMock()
        link_id = uuid.uuid4()
        mappings = MagicMock()
        mappings.one_or_none.return_value = {
            "id": link_id,
            "bucket": "bucket",
            "object_key": "object.bin",
        }
        result = MagicMock()
        result.mappings.return_value = mappings
        db.execute.return_value = result
        monkeypatch.setattr(share.secrets, "randbelow", lambda _limit: 7)

        resolved = asyncio.run(share.resolve_active_link(db, "raw-token"))

        assert resolved == share.ResolvedShareLink(
            id=link_id,
            bucket="bucket",
            object_key="object.bin",
        )
        db.execute.assert_awaited_once()
        statement, parameters = db.execute.await_args.args
        sql = str(statement)
        assert "INSERT INTO share_link_access_counters" in sql
        assert "ON CONFLICT (share_link_id, shard) DO UPDATE" in sql
        assert "revoked IS FALSE" in sql
        assert parameters["token_hash"] == share.hash_token("raw-token")
        assert parameters["shard"] == 7
        db.commit.assert_awaited_once_with()

    def test_missing_expired_or_revoked_link_is_gone(self):
        db = AsyncMock()
        mappings = MagicMock()
        mappings.one_or_none.return_value = None
        result = MagicMock()
        result.mappings.return_value = mappings
        db.execute.return_value = result

        with pytest.raises(share.ShareLinkGone):
            asyncio.run(share.resolve_active_link(db, "invalid-token"))

        db.commit.assert_not_awaited()


class TestListLinks:
    def test_combines_legacy_and_sharded_counter_values(self):
        old_accessed_at = datetime.now(timezone.utc) - timedelta(days=1)
        new_accessed_at = datetime.now(timezone.utc)
        link = ShareLink(
            id=uuid.uuid4(),
            token_hash="a" * 64,
            bucket="bucket",
            object_key="object.bin",
            created_by_email="user@example.com",
            access_count=4,
            last_accessed_at=old_accessed_at,
        )
        result = MagicMock()
        result.all.return_value = [(link, Decimal("6"), new_accessed_at)]
        db = AsyncMock()
        db.execute.return_value = result
        user = MagicMock(is_admin=True)

        links = asyncio.run(share.list_links(db, user))

        assert links == [link]
        assert link.access_count == 10
        assert link.last_accessed_at == new_accessed_at
        statement = db.execute.await_args.args[0]
        assert statement.get_execution_options()["populate_existing"] is True

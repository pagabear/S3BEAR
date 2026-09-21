"""Central bucket-permission logic.

Every access decision on a bucket flows through this module so the rules — and
the hardening around them — live in exactly one place. Previously the same
``fnmatch`` check was copied across ``deps.py``, ``objects.py``, ``images.py``
and ``buckets.py``, and only one copy rejected the character-class patterns
that make ``fnmatch`` a footgun; the others silently evaluated them.

Pure functions here depend only on the standard library, so they are unit
testable without a database.
"""
from __future__ import annotations

from fnmatch import fnmatch
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.user import User

# Maps an API-level action to the boolean column on BucketPermission.
ACTION_MAP: dict[str, str] = {
    "list": "can_list",
    "read": "can_read",
    "write": "can_write",
    "delete": "can_delete",
}

ACTIONS = tuple(ACTION_MAP)


def is_safe_pattern(pattern: str) -> bool:
    """Reject patterns containing character-class brackets.

    ``fnmatch`` treats ``[...]`` as a character class, so a pattern like
    ``prod-[a-z]*`` would match unintended buckets. Permission patterns are
    meant to be plain globs (``*``/``?``), so brackets are disallowed outright.
    """
    return "[" not in pattern and "]" not in pattern


def has_permission(user: "User", bucket_name: str, action: str) -> bool:
    """True if any of the user's groups grants ``action`` on ``bucket_name``.

    Admins implicitly have every permission. Unknown actions raise ``ValueError``.
    """
    attr = ACTION_MAP.get(action)
    if attr is None:
        raise ValueError(f"Unknown action: {action}")
    if user.is_admin:
        return True
    for group in user.groups:
        for perm in group.permissions:
            if (
                is_safe_pattern(perm.bucket_pattern)
                and fnmatch(bucket_name, perm.bucket_pattern)
                and getattr(perm, attr)
            ):
                return True
    return False


def resolve_permissions(user: "User", bucket_name: str) -> dict[str, bool]:
    """Return the full {can_list, can_read, can_write, can_delete} map for a
    user against a bucket. Used by the buckets listing to annotate each row."""
    if user.is_admin:
        return {attr: True for attr in ACTION_MAP.values()}

    perms = {attr: False for attr in ACTION_MAP.values()}
    for group in user.groups:
        for perm in group.permissions:
            if not is_safe_pattern(perm.bucket_pattern):
                continue
            if fnmatch(bucket_name, perm.bucket_pattern):
                for attr in ACTION_MAP.values():
                    if getattr(perm, attr):
                        perms[attr] = True
    return perms

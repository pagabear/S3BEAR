"""Unit tests for the central bucket-permission logic.

These cover the security-critical matching rules — including the fnmatch
character-class hardening that was previously enforced in only one of the four
copies of this check. No database is involved: users, groups and permissions
are lightweight stand-ins with the attributes the logic reads.
"""
import pytest

from app.services import permissions


class _Perm:
    def __init__(self, bucket_pattern, *, can_list=False, can_read=False,
                 can_write=False, can_delete=False):
        self.bucket_pattern = bucket_pattern
        self.can_list = can_list
        self.can_read = can_read
        self.can_write = can_write
        self.can_delete = can_delete


class _Group:
    def __init__(self, permissions):
        self.permissions = permissions


class _User:
    def __init__(self, groups=(), is_admin=False):
        self.groups = list(groups)
        self.is_admin = is_admin


def _user_with(*perms, is_admin=False):
    return _User(groups=[_Group(list(perms))], is_admin=is_admin)


class TestIsSafePattern:
    def test_plain_globs_are_safe(self):
        assert permissions.is_safe_pattern("*")
        assert permissions.is_safe_pattern("prod-*")
        assert permissions.is_safe_pattern("logs-?")

    @pytest.mark.parametrize("pattern", ["prod-[a-z]*", "x]y", "[abc]"])
    def test_character_classes_are_rejected(self, pattern):
        assert not permissions.is_safe_pattern(pattern)


class TestHasPermission:
    def test_admin_always_allowed(self):
        admin = _User(is_admin=True)
        assert permissions.has_permission(admin, "anything", "delete")

    def test_exact_match_grants(self):
        user = _user_with(_Perm("photos", can_read=True))
        assert permissions.has_permission(user, "photos", "read")

    def test_glob_match_grants(self):
        user = _user_with(_Perm("prod-*", can_write=True))
        assert permissions.has_permission(user, "prod-images", "write")

    def test_action_bit_must_be_set(self):
        user = _user_with(_Perm("photos", can_read=True))
        # Pattern matches but the delete bit is off.
        assert not permissions.has_permission(user, "photos", "delete")

    def test_no_match_denies(self):
        user = _user_with(_Perm("photos", can_read=True))
        assert not permissions.has_permission(user, "videos", "read")

    def test_character_class_pattern_never_matches(self):
        # The hardening: even though fnmatch("prod-a", "prod-[a-z]") is True,
        # bracket patterns are rejected before matching so they grant nothing.
        user = _user_with(_Perm("prod-[a-z]", can_read=True))
        assert not permissions.has_permission(user, "prod-a", "read")

    def test_any_matching_permission_across_groups_grants(self):
        user = _User(groups=[
            _Group([_Perm("a", can_read=True)]),
            _Group([_Perm("b", can_write=True)]),
        ])
        assert permissions.has_permission(user, "b", "write")

    def test_unknown_action_raises(self):
        user = _user_with(_Perm("*", can_read=True))
        with pytest.raises(ValueError):
            permissions.has_permission(user, "photos", "execute")


class TestResolvePermissions:
    def test_admin_gets_everything(self):
        admin = _User(is_admin=True)
        perms = permissions.resolve_permissions(admin, "any")
        assert perms == {"can_list": True, "can_read": True,
                         "can_write": True, "can_delete": True}

    def test_bits_are_unioned_across_matching_permissions(self):
        user = _User(groups=[
            _Group([_Perm("data-*", can_read=True)]),
            _Group([_Perm("data-*", can_write=True)]),
        ])
        perms = permissions.resolve_permissions(user, "data-1")
        assert perms["can_read"] and perms["can_write"]
        assert not perms["can_delete"]

    def test_non_matching_leaves_all_false(self):
        user = _user_with(_Perm("other", can_read=True, can_write=True))
        perms = permissions.resolve_permissions(user, "mine")
        assert perms == {"can_list": False, "can_read": False,
                         "can_write": False, "can_delete": False}

    def test_character_class_pattern_grants_nothing(self):
        user = _user_with(_Perm("prod-[a-z]", can_read=True))
        perms = permissions.resolve_permissions(user, "prod-a")
        assert not any(perms.values())

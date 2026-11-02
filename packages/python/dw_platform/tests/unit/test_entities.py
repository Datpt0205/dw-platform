import uuid

import pytest

from dw_kernel.ids import EntityId, TenantId, UserId, WorkspaceId
from dw_platform.domain.entities import (
    Membership,
    Role,
    User,
)

pytestmark = pytest.mark.unit


def test_user_requires_subject() -> None:
    with pytest.raises(ValueError, match="subject"):
        User(id=UserId(uuid.uuid4()), subject=" ", email=None, display_name="An")


def test_role_key_snake_case() -> None:
    Role(key="platform_admin", name="Admin", scopes=frozenset({"platform.admin"}))
    with pytest.raises(ValueError, match="snake_case"):
        Role(key="Platform-Admin", name="Admin", scopes=frozenset())


def test_membership_requires_roles() -> None:
    with pytest.raises(ValueError, match="at least one role"):
        Membership(
            id=EntityId(uuid.uuid4()),
            tenant_id=TenantId(uuid.uuid4()),
            workspace_id=WorkspaceId(uuid.uuid4()),
            user_id=UserId(uuid.uuid4()),
            role_keys=frozenset(),
        )

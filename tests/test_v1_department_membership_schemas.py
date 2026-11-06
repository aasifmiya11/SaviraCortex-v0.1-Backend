import pytest
from pydantic import ValidationError

from app.schemas.v1.department_memberships import DepartmentMembershipCreateRequest


def test_department_membership_requires_user_id():
    payload = DepartmentMembershipCreateRequest(user_id="2d6b8f3a-5e6c-4a3b-8f4d-9a0b1c2d3e4f")
    assert str(payload.user_id) == "2d6b8f3a-5e6c-4a3b-8f4d-9a0b1c2d3e4f"


def test_department_membership_rejects_invalid_user_id():
    with pytest.raises(ValidationError):
        DepartmentMembershipCreateRequest(user_id="not-a-uuid")


def test_department_membership_rejects_untrusted_fields():
    with pytest.raises(ValidationError):
        DepartmentMembershipCreateRequest(user_id="2d6b8f3a-5e6c-4a3b-8f4d-9a0b1c2d3e4f", organization_id="untrusted")
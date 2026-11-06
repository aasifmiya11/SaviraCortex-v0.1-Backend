import pytest
from pydantic import ValidationError

from app.schemas.v1.memberships import OrganizationMembershipCreateRequest, OrganizationMembershipUpdateRequest


def test_membership_create_defaults_to_member():
    payload = OrganizationMembershipCreateRequest(user_id="2d6b8f3a-5e6c-4a3b-8f4d-9a0b1c2d3e4f")
    assert payload.role == "member"


@pytest.mark.parametrize("role", ["owner", " OWNER ", "invalid", " "])
def test_membership_create_rejects_unsupported_roles(role):
    with pytest.raises(ValidationError):
        OrganizationMembershipCreateRequest(user_id="2d6b8f3a-5e6c-4a3b-8f4d-9a0b1c2d3e4f", role=role)


def test_membership_create_normalizes_role():
    payload = OrganizationMembershipCreateRequest(user_id="2d6b8f3a-5e6c-4a3b-8f4d-9a0b1c2d3e4f", role=" ADMIN ")
    assert payload.role == "admin"


def test_membership_update_accepts_member_or_admin():
    assert OrganizationMembershipUpdateRequest(role="member").role == "member"
    assert OrganizationMembershipUpdateRequest(role="admin").role == "admin"


def test_membership_update_rejects_owner_role():
    with pytest.raises(ValidationError):
        OrganizationMembershipUpdateRequest(role="owner")


def test_membership_create_rejects_untrusted_fields():
    with pytest.raises(ValidationError):
        OrganizationMembershipCreateRequest(user_id="2d6b8f3a-5e6c-4a3b-8f4d-9a0b1c2d3e4f", organization_id="untrusted")
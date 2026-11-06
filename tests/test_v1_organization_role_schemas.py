import pytest
from pydantic import ValidationError

from app.schemas.v1.organization_roles import OrganizationRoleCreateRequest


def test_role_create_trims_name_and_description():
    payload = OrganizationRoleCreateRequest(name="  Knowledge Manager  ", description="  Manages knowledge  ")
    assert payload.name == "Knowledge Manager"
    assert payload.description == "Manages knowledge"


def test_role_create_converts_blank_description_to_none():
    payload = OrganizationRoleCreateRequest(name="Auditor", description="   ")
    assert payload.description is None


@pytest.mark.parametrize("name", ["", " ", "A", "  A  "])
def test_role_create_rejects_short_or_blank_names(name):
    with pytest.raises(ValidationError):
        OrganizationRoleCreateRequest(name=name)


def test_role_create_rejects_unexpected_fields():
    with pytest.raises(ValidationError):
        OrganizationRoleCreateRequest(name="Auditor", organization_id="untrusted-org")

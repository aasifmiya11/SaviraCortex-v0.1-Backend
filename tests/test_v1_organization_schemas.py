import pytest
from pydantic import ValidationError

from app.schemas.v1.organizations import OrganizationCreateRequest, OrganizationUpdateRequest


def test_organization_create_trims_name():
    payload = OrganizationCreateRequest(name="  Savira Cortex  ")
    assert payload.name == "Savira Cortex"


def test_organization_update_trims_name():
    payload = OrganizationUpdateRequest(name="  Research  ")
    assert payload.name == "Research"


@pytest.mark.parametrize("name", ["", " ", "A", "  A  "])
def test_organization_create_rejects_short_or_blank_names(name):
    with pytest.raises(ValidationError):
        OrganizationCreateRequest(name=name)


def test_organization_create_rejects_unexpected_fields():
    with pytest.raises(ValidationError):
        OrganizationCreateRequest(name="Engineering", owner_id="untrusted-user")

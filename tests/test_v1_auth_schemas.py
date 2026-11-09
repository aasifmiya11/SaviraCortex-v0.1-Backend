import pytest
from pydantic import ValidationError

from app.schemas.v1.auth import OrganizationSignupRequest


def test_signup_request_strips_whitespace():
    payload = OrganizationSignupRequest(
        organization_name="  Acme Labs  ",
        admin_name="  Alex Doe  ",
        departments=[{"name":" Engineering "}, {"name":"HR"}],
        roles=[{"name":" Manager "}, {"name":"Developer"}],
    )

    assert payload.organization_name == "Acme Labs"
    assert payload.admin_name == "Alex Doe"
    assert [item.name for item in payload.departments] == ["Engineering", "HR"]
    assert [item.name for item in payload.roles] == ["Manager", "Developer"]


def test_signup_request_rejects_extra_fields():
    with pytest.raises(ValidationError):
        OrganizationSignupRequest(
            organization_name="Acme Labs",
            admin_name="Alex Doe",
            departments=[{"name":"Engineering","description":"Builds products"}],
            roles=[{"name":"Manager","description":"Team manager"}],
            email="alex@example.com",
        )


def test_signup_request_rejects_blank_names():
    with pytest.raises(ValidationError):
        OrganizationSignupRequest(
            organization_name="   ",
            admin_name="Alex Doe",
            departments=[{"name":"Engineering"}],
            roles=[{"name":"Manager"}],
        )

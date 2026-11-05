import pytest
from pydantic import ValidationError

from app.schemas.v1.auth import OrganizationSignupRequest


def test_signup_request_strips_whitespace():
    payload = OrganizationSignupRequest(
        organization_name="  Acme Labs  ",
        admin_name="  Alex Doe  ",
    )

    assert payload.organization_name == "Acme Labs"
    assert payload.admin_name == "Alex Doe"


def test_signup_request_rejects_extra_fields():
    with pytest.raises(ValidationError):
        OrganizationSignupRequest(
            organization_name="Acme Labs",
            admin_name="Alex Doe",
            email="alex@example.com",
        )


def test_signup_request_rejects_blank_names():
    with pytest.raises(ValidationError):
        OrganizationSignupRequest(
            organization_name="   ",
            admin_name="Alex Doe",
        )

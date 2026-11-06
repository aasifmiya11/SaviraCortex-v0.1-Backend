import pytest
from pydantic import ValidationError

from app.schemas.v1.invitations import InvitationAcceptRequest, InvitationCreateRequest


def test_invitation_create_normalizes_candidate_and_email():
    payload = InvitationCreateRequest(
        email="  EMPLOYEE@EXAMPLE.COM ",
        candidate_name="  Aanya   Sharma  ",
    )

    assert payload.email == "employee@example.com"
    assert payload.candidate_name == "Aanya Sharma"
    assert payload.role == "member"


def test_invitation_accept_requires_name_and_password_but_phone_is_optional():
    payload = InvitationAcceptRequest(
        token="x" * 32,
        full_name="  Aanya   Sharma ",
        password="a-secure-password",
    )

    assert payload.full_name == "Aanya Sharma"
    assert payload.password == "a-secure-password"
    assert payload.phone_number is None


def test_invitation_accept_normalizes_optional_phone():
    payload = InvitationAcceptRequest(
        token="x" * 32,
        full_name="Aanya Sharma",
        password="a-secure-password",
        phone_number="  +919876543210  ",
    )

    assert payload.phone_number == "+919876543210"


def test_invitation_accept_rejects_short_password():
    with pytest.raises(ValidationError):
        InvitationAcceptRequest(
            token="x" * 32,
            full_name="Aanya Sharma",
            password="short",
        )

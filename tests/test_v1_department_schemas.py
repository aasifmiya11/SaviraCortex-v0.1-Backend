import pytest
from pydantic import ValidationError

from app.schemas.v1.departments import DepartmentCreateRequest


def test_department_request_trims_name_and_description():
    payload = DepartmentCreateRequest(name="  Engineering  ", description="  Builds things  ")
    assert payload.name == "Engineering"
    assert payload.description == "Builds things"


def test_department_request_converts_blank_description_to_none():
    payload = DepartmentCreateRequest(name="Research", description="   ")
    assert payload.description is None


@pytest.mark.parametrize("name", ["", " ", "A", "  A  "])
def test_department_request_rejects_short_or_blank_names(name):
    with pytest.raises(ValidationError):
        DepartmentCreateRequest(name=name)


def test_department_request_rejects_unexpected_fields():
    with pytest.raises(ValidationError):
        DepartmentCreateRequest(name="Finance", organization_id="untrusted-client-org")

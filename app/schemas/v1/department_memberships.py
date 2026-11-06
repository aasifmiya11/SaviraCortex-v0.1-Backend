from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DepartmentMembershipCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: UUID


class DepartmentMembershipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    organization_id: UUID
    user_id: UUID
    department_id: UUID
    created_at: datetime
    email: str | None = None
    display_name: str | None = None
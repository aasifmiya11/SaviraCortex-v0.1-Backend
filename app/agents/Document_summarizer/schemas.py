from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


DepartmentConfidence = Literal["high", "medium", "low"]


class DocumentSummarizerOutput(BaseModel):

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    title: str = Field(
        description="The actual or inferred title of the document."
    )

    document_type: str = Field(
        description="The primary category of the document."
    )

    department: str | None = Field(
        default=None,
        description=(
            "The department most likely responsible for owning, "
            "maintaining, or administering the document."
        ),
    )

    department_confidence: DepartmentConfidence | None = Field(
        default=None,
        description=(
            "Confidence in the inferred department: high, medium, "
            "or low. Must be null when department is null."
        ),
    )

    description: str = Field(
        description=(
            "A concise description of the document's purpose and scope."
        )
    )

    summary: str = Field(
        description=(
            "A comprehensive overview of the document's main content."
        )
    )

    @model_validator(mode="after")
    def validate_department_confidence(self):

        if (
            self.department is None
            and self.department_confidence is not None
        ):
            raise ValueError(
                "department_confidence must be null "
                "when department is null."
            )

        if (
            self.department is not None
            and self.department_confidence is None
        ):
            raise ValueError(
                "department_confidence is required "
                "when department is provided."
            )

        return self
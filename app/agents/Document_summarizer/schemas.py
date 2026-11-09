from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


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

    person_name: str | None = Field(default=None, description="For a resume/CV only, the person's full name exactly as stated; otherwise null.")
    email_addresses: list[str] = Field(default_factory=list, description="Email addresses explicitly present in the document, normalized to lowercase.")
    phone_numbers: list[str] = Field(default_factory=list, description="Phone numbers explicitly present in the document, preserving country codes when shown.")

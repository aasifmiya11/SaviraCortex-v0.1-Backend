from pydantic import BaseModel, ConfigDict, Field, field_validator


class CompressedDocument(BaseModel):
    """Compressed content corresponding to exactly one input document."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    index: int = Field(ge=1)
    compressed_content: str = Field(min_length=1)

    @field_validator("compressed_content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        if not value:
            raise ValueError("Compressed content cannot be empty.")
        return value


class ContextCompressionOutput(BaseModel):
    """Ordered one-to-one compression result."""

    model_config = ConfigDict(extra="forbid")
    documents: list[CompressedDocument] = Field(min_length=1)

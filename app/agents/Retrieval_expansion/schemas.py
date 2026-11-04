from pydantic import BaseModel, ConfigDict, Field, field_validator


class RetrievalExpansionOutput(BaseModel):
    """Retrieval-only query and hypothetical-answer guidance."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    rewritten_query: str = Field(
        min_length=1,
        description=(
            "A focused, standalone retrieval query targeting the missing "
            "information identified by the evidence evaluator."
        ),
    )
    hypothetical_answer: str = Field(
        min_length=1,
        description=(
            "A hypothetical answer-shaped passage used only as semantic "
            "retrieval guidance, never as verified evidence."
        ),
    )

    @field_validator("rewritten_query", "hypothetical_answer")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        if not value:
            raise ValueError("Output text cannot be empty.")
        return value

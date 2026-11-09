from pydantic import BaseModel, ConfigDict, Field, model_validator


class EvidenceEvaluation(BaseModel):
    """Structured judgment of whether retrieved evidence answers the query."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    is_sufficient: bool = Field(
        description=(
            "True only when the retrieved evidence supports every material "
            "information requirement in the user's current question."
        )
    )
    missing_information: list[str] = Field(
        default_factory=list,
        description=(
            "Specific question requirements that the retrieved evidence "
            "does not adequately support. Empty when evidence is sufficient."
        ),
    )

    @model_validator(mode="after")
    def validate_sufficiency_details(self) -> "EvidenceEvaluation":
        if self.is_sufficient and self.missing_information:
            raise ValueError(
                "missing_information must be empty when evidence is sufficient."
            )

        if not self.is_sufficient and not self.missing_information:
            raise ValueError(
                "missing_information is required when evidence is insufficient."
            )

        if any(not item for item in self.missing_information):
            raise ValueError("missing_information entries cannot be empty.")

        normalized = [item.casefold() for item in self.missing_information]
        if len(normalized) != len(set(normalized)):
            raise ValueError("missing_information entries must be unique.")

        return self

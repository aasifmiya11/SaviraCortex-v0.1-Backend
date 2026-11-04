from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class GenerationStatus(str, Enum):
    ANSWERED = "answered"
    PARTIAL = "partial"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class AnswerSegment(BaseModel):
    """One answer segment and the evidence references supporting it."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    text: str = Field(
        min_length=1,
        description="A concise sentence or paragraph in the generated answer.",
    )
    citations: list[str] = Field(
        default_factory=list,
        description=(
            "Evidence IDs supporting the factual claims in this segment. "
            "Use only IDs supplied in the retrieved evidence."
        ),
    )


class GenerationOutput(BaseModel):
    """Structured response produced by the generation agent."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    status: GenerationStatus = Field(
        description=(
            "Whether the answer is supported completely, partially, "
            "or cannot be determined from the supplied evidence."
        )
    )
    segments: list[AnswerSegment] = Field(
        min_length=1,
        description=(
            "Ordered answer segments. Attach citations to the segment "
            "containing the claims they support."
        ),
    )

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


QuestionStyle = Literal["context_dependent", "balanced", "self_contained"]
ContextDependency = Literal[
    "requires_context",
    "helpful_but_not_required",
    "does_not_require_context",
]


class GeneratedQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(
        min_length=8,
        max_length=500,
        description="A natural user query grounded in the supplied evidence.",
    )
    style: QuestionStyle = Field(
        description="The intended relationship between the question and conversation context.",
    )
    context_dependency: ContextDependency = Field(
        description="Whether the question requires prior conversation context.",
    )
    generation_rationale: str = Field(
        min_length=1,
        max_length=240,
        description="A concise explanation of the question variant's intended style.",
    )

    @model_validator(mode="after")
    def validate_style_dependency(self) -> GeneratedQuestion:
        expected = {
            "context_dependent": "requires_context",
            "balanced": "helpful_but_not_required",
            "self_contained": "does_not_require_context",
        }
        if self.context_dependency != expected[self.style]:
            raise ValueError(
                "context_dependency must match the selected question style."
            )
        return self


class QuestionGenerationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    questions: list[GeneratedQuestion] = Field(
        min_length=1,
        max_length=3,
        description="One to three distinct question variants for this candidate.",
    )

    @model_validator(mode="after")
    def validate_unique_questions(self) -> QuestionGenerationOutput:
        normalized = [
            re.sub(r"\s+", " ", item.question).strip().casefold()
            for item in self.questions
        ]
        if len(normalized) != len(set(normalized)):
            raise ValueError("Question variants must not be duplicates.")
        return self

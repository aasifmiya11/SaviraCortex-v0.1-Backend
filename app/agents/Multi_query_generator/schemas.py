from pydantic import BaseModel, ConfigDict, Field, field_validator


class MultiQueryGeneratorOutput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    queries: list[str] = Field(
        description="Distinct contextualized search queries.",
        min_length=1,
    )

    @field_validator("queries")
    @classmethod
    def validate_queries(cls, queries: list[str]) -> list[str]:
        if any(not query for query in queries):
            raise ValueError("Queries cannot be empty.")

        normalized = [query.casefold() for query in queries]

        if len(normalized) != len(set(normalized)):
            raise ValueError("Queries must be unique.")

        return queries
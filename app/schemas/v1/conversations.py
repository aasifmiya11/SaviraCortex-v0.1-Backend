from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConversationRenameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=255)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        title = " ".join(value.split()).strip()
        if not title:
            raise ValueError("Conversation title cannot be blank.")
        return title

from __future__ import annotations

from collections.abc import Sequence
from enum import Enum

from langchain_core.messages import BaseMessage

from app.core.config import settings


class ModelRoute(str, Enum):
    TEXT = "text"
    VISION = "vision"


class ModelRoutingError(RuntimeError):
    """Raised when the request requires a model route that is not configured."""


class ModelRouter:
    """Select a generation model from the modalities present in chat history."""

    @staticmethod
    def has_image_input(messages: Sequence[BaseMessage] | None) -> bool:
        for message in messages or []:
            additional_kwargs = getattr(message, "additional_kwargs", None) or {}
            if additional_kwargs.get("image_attachments"):
                return True
            content = getattr(message, "content", None)
            if isinstance(content, list) and any(
                isinstance(block, dict) and block.get("type") == "image_url"
                for block in content
            ):
                return True
        return False

    def select_route(self, messages: Sequence[BaseMessage] | None) -> ModelRoute:
        if not self.has_image_input(messages):
            return ModelRoute.TEXT

        if not settings.OPENAI_VISION_ENABLED:
            raise ModelRoutingError(
                "The currently configured model does not support image input. "
                "Please switch to a vision-capable model or send a text-only message."
            )
        if not settings.OPENAI_VISION_MODEL:
            raise ModelRoutingError(
                "No vision-capable model is configured. Please contact your administrator."
            )
        if not settings.OPENAI_BASE_URL or not settings.OPENAI_API_KEY:
            raise ModelRoutingError(
                "The vision model provider is not configured. Please contact your administrator."
            )
        return ModelRoute.VISION

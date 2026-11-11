from uuid import uuid4

import pytest
from langchain_core.messages import HumanMessage

from app.agents.Generation.agent import GenerationAgent
from app.core.config import settings
from app.schemas.v1.generation import ImageAttachmentInput
from app.services.generation.image_attachments import (
    _validate_image_bytes,
    prepare_image_attachments,
)


def test_image_upload_is_disabled_until_model_vision_is_verified(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_VISION_ENABLED", False)
    image = ImageAttachmentInput(
        name="equation.png",
        content_type="image/png",
        data_url="data:image/png;base64,iVBORw0KGgo=",
    )

    with pytest.raises(ValueError, match="does not support image input"):
        prepare_image_attachments(
            [image],
            organization_id=uuid4(),
            user_id=uuid4(),
            request_id=uuid4(),
        )


@pytest.mark.parametrize(
    ("content", "content_type"),
    [
        (b"\x89PNG\r\n\x1a\nrest", "image/png"),
        (b"\xff\xd8\xffrest", "image/jpeg"),
        (b"RIFF0000WEBPrest", "image/webp"),
    ],
)
def test_validates_image_signatures(content, content_type):
    _validate_image_bytes(content, content_type)


def test_rejects_mismatched_image_signature():
    with pytest.raises(ValueError, match="do not match"):
        _validate_image_bytes(b"not an image", "image/png")


def test_generation_agent_recognizes_multimodal_history_without_document_evidence():
    message = HumanMessage(
        content=[
            {"type": "text", "text": "Solve this equation."},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
        ]
    )

    assert GenerationAgent._has_image_input([message]) is True
    assert GenerationAgent._has_image_input([HumanMessage(content="text only")]) is False

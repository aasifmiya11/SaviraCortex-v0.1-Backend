import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.core.config import settings
from app.llm.model_router import ModelRoute, ModelRouter, ModelRoutingError


def test_text_only_turn_uses_text_route():
    assert ModelRouter().select_route([HumanMessage(content="Hello")]) is ModelRoute.TEXT


def test_image_turn_uses_vision_route_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_VISION_ENABLED", True)
    monkeypatch.setattr(settings, "OPENAI_VISION_MODEL", "writer.palmyra-vision-7b")
    monkeypatch.setattr(settings, "OPENAI_BASE_URL", "https://bedrock-mantle.example/v1")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-key")
    image_message = HumanMessage(
        content=[
            {"type": "text", "text": "What is in this picture?"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
        ]
    )

    assert ModelRouter().select_route([image_message]) is ModelRoute.VISION


def test_image_reference_in_checkpoint_routes_to_vision(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_VISION_ENABLED", True)
    monkeypatch.setattr(settings, "OPENAI_VISION_MODEL", "writer.palmyra-vision-7b")
    monkeypatch.setattr(settings, "OPENAI_BASE_URL", "https://bedrock-mantle.example/v1")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-key")
    image_message = HumanMessage(
        content="Please describe it.",
        additional_kwargs={"image_attachments": [{"storage_key": "private/key"}]},
    )

    assert ModelRouter().select_route([image_message]) is ModelRoute.VISION


def test_image_turn_fails_clearly_when_vision_is_disabled(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_VISION_ENABLED", False)
    image_message = HumanMessage(
        content=[{"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}}]
    )

    with pytest.raises(ModelRoutingError, match="does not support image input"):
        ModelRouter().select_route([image_message])


def test_multimodal_prompt_uses_alternating_roles_and_embeds_trusted_instructions():
    from app.agents.Generation.agent import GenerationAgent

    image_message = HumanMessage(
        content=[
            {"type": "text", "text": "Describe this image."},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
        ]
    )
    history = [
        HumanMessage(content="Earlier question"),
        AIMessage(content="Earlier answer"),
        image_message,
    ]
    payload = GenerationAgent._build_vision_payload(
        "Describe this image.", [], history
    )
    from app.agents.Generation.prompts import get_generation_prompt
    formatted = get_generation_prompt(multimodal=True).format_messages(**payload)

    assert [message.type for message in formatted] == ["human", "ai", "human"]
    current_content = formatted[-1].content
    assert any(
        isinstance(block, dict)
        and block.get("type") == "text"
        and "TRUSTED SAVIRACORTEX ASSISTANT INSTRUCTIONS" in block.get("text", "")
        for block in current_content
    )
    assert sum(
        1 for block in current_content
        if isinstance(block, dict) and block.get("type") == "image_url"
    ) == 1

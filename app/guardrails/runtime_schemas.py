from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class GuardrailAction(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"
    REDACT = "redact"
    REDIRECT = "redirect"
    ERROR = "error"
    HASH = "hash"


class GuardrailFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    triggered: bool
    reason: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=0)
    entity_type: str | None = None


class GuardrailPolicyPatch(BaseModel):
    """Tenant-editable guardrail policy. Platform-mandated checks are immutable."""

    model_config = ConfigDict(extra="forbid")

    allowed_topics: list[str] = Field(default_factory=list, max_length=100)
    restricted_topics: list[str] = Field(default_factory=list, max_length=100)
    off_topic_message: str = Field(
        default="I can help with topics related to this organization's knowledge. Could you rephrase your question?",
        max_length=1000,
    )
    custom_input_policy: str = Field(default="", max_length=5000)
    custom_output_policy: str = Field(default="", max_length=5000)
    input_enabled: dict[str, bool] = Field(default_factory=dict)
    output_enabled: dict[str, bool] = Field(default_factory=dict)
    input_actions: dict[str, GuardrailAction] = Field(default_factory=dict)
    output_actions: dict[str, GuardrailAction] = Field(default_factory=dict)
    pii_require_consent: bool = True
    pii_allow_send_as_is: bool = True
    topicality_enabled: bool = True
    topicality_high_threshold: float = Field(default=0.60, ge=0.0, le=1.0)
    topicality_low_threshold: float = Field(default=0.20, ge=0.0, le=1.0)
    history_window_exchanges: int = Field(default=5, ge=0, le=20)

    @field_validator("allowed_topics", "restricted_topics")
    @classmethod
    def clean_topics(cls, values: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(item.strip() for item in values if item.strip()))
        if any(len(item) > 200 for item in cleaned):
            raise ValueError("Each topic description must be at most 200 characters.")
        return cleaned

    @field_validator("topicality_low_threshold")
    @classmethod
    def thresholds_are_ordered(cls, value: float, info) -> float:
        high = info.data.get("topicality_high_threshold", 0.60)
        if value >= high:
            raise ValueError("The low topicality threshold must be below the high threshold.")
        return value


class EffectiveGuardrailPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    allowed_topics: list[str] = Field(default_factory=list)
    restricted_topics: list[str] = Field(default_factory=list)
    off_topic_message: str
    custom_input_policy: str = ""
    custom_output_policy: str = ""
    input_enabled: dict[str, bool]
    output_enabled: dict[str, bool]
    input_actions: dict[str, GuardrailAction]
    output_actions: dict[str, GuardrailAction]
    pii_require_consent: bool = True
    pii_allow_send_as_is: bool = True
    topicality_enabled: bool = True
    topicality_high_threshold: float = 0.60
    topicality_low_threshold: float = 0.20
    history_window_exchanges: int = 5


def default_guardrail_policy() -> EffectiveGuardrailPolicy:
    input_categories = {
        "direct_jailbreak": True,
        "indirect_prompt_injection": True,
        "role_manipulation": True,
        "prompt_extraction": True,
        "toxicity": True,
        "sexual_content": True,
        "hate_discrimination": True,
        "violence_self_harm": True,
        "organization_policy": True,
        "topicality": True,
    }
    output_categories = {
        "pii_leakage": True,
        "secret_leakage": True,
        "system_prompt_leakage": True,
        "unsafe_instruction_compliance": True,
        "toxicity": True,
        "sexual_content": True,
        "hate_discrimination": True,
        "violence_self_harm": True,
        "off_topic": True,
        "grounding": True,
        "organization_policy": True,
    }
    block = GuardrailAction.BLOCK
    return EffectiveGuardrailPolicy(
        off_topic_message="I can help with topics related to this organization's knowledge. Could you rephrase your question?",
        input_enabled=input_categories,
        output_enabled=output_categories,
        input_actions={key: block for key in input_categories if key != "topicality"},
        output_actions={key: block for key in output_categories},
    )


def resolve_effective_policy(raw: dict[str, Any] | None) -> EffectiveGuardrailPolicy:
    """Merge tenant overrides onto platform defaults without allowing mandatory bypasses."""
    base = default_guardrail_policy()
    if not isinstance(raw, dict):
        return base
    # Graph snapshots include this server-owned field; tenant PATCH payloads do not set it.
    version = raw.get("version", 1)
    if version != 1:
        raise ValueError(f"Unsupported guardrail policy snapshot version: {version}")
    tenant_values = dict(raw)
    tenant_values.pop("version", None)
    patch = GuardrailPolicyPatch.model_validate(tenant_values)
    data = base.model_dump(mode="python")
    data.update({
        "allowed_topics": patch.allowed_topics,
        "restricted_topics": patch.restricted_topics,
        "off_topic_message": patch.off_topic_message,
        "custom_input_policy": patch.custom_input_policy,
        "custom_output_policy": patch.custom_output_policy,
        "pii_require_consent": patch.pii_require_consent,
        "pii_allow_send_as_is": patch.pii_allow_send_as_is,
        "topicality_enabled": patch.topicality_enabled,
        "topicality_high_threshold": patch.topicality_high_threshold,
        "topicality_low_threshold": patch.topicality_low_threshold,
        "history_window_exchanges": patch.history_window_exchanges,
    })
    for field, overrides in (
        ("input_enabled", patch.input_enabled),
        ("output_enabled", patch.output_enabled),
        ("input_actions", patch.input_actions),
        ("output_actions", patch.output_actions),
    ):
        data[field] = {**data[field], **{key: value for key, value in overrides.items()}}
    # Mandatory platform protections cannot be disabled or made permissive by a tenant.
    data["input_enabled"]["direct_jailbreak"] = True
    data["input_enabled"]["indirect_prompt_injection"] = True
    data["input_actions"]["direct_jailbreak"] = GuardrailAction.BLOCK
    data["input_actions"]["indirect_prompt_injection"] = GuardrailAction.BLOCK
    data["output_enabled"]["pii_leakage"] = True
    data["output_enabled"]["secret_leakage"] = True
    data["output_enabled"]["system_prompt_leakage"] = True
    if data["output_actions"]["pii_leakage"] == GuardrailAction.ALLOW:
        data["output_actions"]["pii_leakage"] = GuardrailAction.BLOCK
    data["output_actions"]["secret_leakage"] = GuardrailAction.BLOCK
    data["output_actions"]["system_prompt_leakage"] = GuardrailAction.BLOCK
    return EffectiveGuardrailPolicy.model_validate(data)

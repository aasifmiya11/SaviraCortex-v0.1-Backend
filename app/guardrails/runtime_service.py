from __future__ import annotations

import logging
import math
from functools import lru_cache
from typing import Any

from app.core.config import settings
from app.guardrails.pii_detector import detect_pii, redact_pii
from app.guardrails.runtime_jev import (
    INPUT_CATEGORIES,
    OUTPUT_CATEGORIES,
    RuntimeJEVJudge,
)
from app.guardrails.runtime_schemas import (
    EffectiveGuardrailPolicy,
    GuardrailAction,
)
from app.guardrails.secret_detector import detect_secrets

logger = logging.getLogger(__name__)


class GuardrailBlockedError(RuntimeError):
    def __init__(self, message: str, findings: list[dict[str, Any]] | None = None):
        self.message = message
        self.findings = findings or []
        super().__init__(message)


class GuardrailConsentRequiredError(RuntimeError):
    def __init__(self, *, redacted_preview: str, entities: list[str], allowed_actions: list[str]):
        self.redacted_preview = redacted_preview
        self.entities = entities
        self.allowed_actions = allowed_actions
        super().__init__("Personal information was detected. Choose how to proceed.")


class RuntimeGuardrailService:
    """Runs deterministic detectors, JEV classification and policy enforcement."""

    def __init__(self, judge: RuntimeJEVJudge | None = None) -> None:
        self.judge = judge or RuntimeJEVJudge()

    @staticmethod
    def _action(
        category: str,
        policy: EffectiveGuardrailPolicy,
        *,
        output: bool,
    ) -> GuardrailAction:
        actions = policy.output_actions if output else policy.input_actions
        return actions.get(category, GuardrailAction.BLOCK)

    @staticmethod
    def _enabled(
        category: str,
        policy: EffectiveGuardrailPolicy,
        *,
        output: bool,
    ) -> bool:
        enabled = policy.output_enabled if output else policy.input_enabled
        return enabled.get(category, True)

    @staticmethod
    def _history_context(history: list[Any] | None, max_exchanges: int) -> list[dict[str, str]]:
        """Serialize only a bounded recent window; history is explicitly untrusted."""
        items: list[dict[str, str]] = []
        for message in history or []:
            role = getattr(message, "type", None) or getattr(message, "role", None) or "unknown"
            content = getattr(message, "content", "")
            if not isinstance(content, str):
                continue
            if role in {"human", "user"}:
                role = "user"
            elif role in {"ai", "assistant"}:
                role = "assistant"
            else:
                continue
            items.append({"role": role, "content": content[:4000]})
        if max_exchanges <= 0:
            return []
        return items[-(max_exchanges * 2):]

    @staticmethod
    def _organization_policy_text(
        policy: EffectiveGuardrailPolicy,
        *,
        include_output: bool = False,
    ) -> str:
        parts = [
            "Allowed topics: " + "; ".join(policy.allowed_topics),
            "Restricted topics: " + "; ".join(policy.restricted_topics),
            "Organization input policy: " + policy.custom_input_policy,
        ]
        if include_output:
            parts.append("Organization output policy: " + policy.custom_output_policy)
        return "\n".join(parts)

    @staticmethod
    def _serialize_evidence(evidence: list[Any] | None) -> list[dict[str, Any]]:
        serialized: list[dict[str, Any]] = []
        for item in (evidence or [])[:20]:
            if isinstance(item, dict):
                content = item.get("page_content") or item.get("content") or item.get("text") or ""
                metadata = item.get("metadata") or {}
            else:
                content = getattr(item, "page_content", "") or getattr(item, "content", "")
                metadata = getattr(item, "metadata", {}) or {}
            safe_metadata: dict[str, str] = {}
            if isinstance(metadata, dict):
                for key in ("source", "title", "page", "document_id", "chunk_id"):
                    value = metadata.get(key)
                    if isinstance(value, (str, int, float)):
                        safe_metadata[key] = str(value)[:300]
            serialized.append({
                "content": str(content)[:3000],
                "metadata": safe_metadata,
            })
        return serialized

    @staticmethod
    @lru_cache(maxsize=256)
    def _topic_vectors(topics: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        from app.rag.embeddings.jina_embeddings import JinaEmbeddingClient

        return tuple(tuple(vector) for vector in JinaEmbeddingClient().embed_documents(list(topics)))

    @classmethod
    def _embedding_similarity(cls, query: str, topics: list[str]) -> float:
        if not topics:
            return 1.0
        from app.rag.embeddings.jina_embeddings import JinaEmbeddingClient

        client = JinaEmbeddingClient()
        query_vector = client.embed_query(query)
        topic_vectors = cls._topic_vectors(tuple(topics))
        if not query_vector or not topic_vectors:
            raise RuntimeError("Topic embedding service returned no vectors.")
        scores = [
            sum(a * b for a, b in zip(query_vector, vector))
            / max(1e-12, math.sqrt(sum(a * a for a in query_vector)) * math.sqrt(sum(b * b for b in vector)))
            for vector in topic_vectors
        ]
        return max(scores)

    async def inspect_input(
        self,
        *,
        query: str,
        history: list[Any] | None,
        policy: EffectiveGuardrailPolicy,
    ) -> dict[str, Any]:
        import asyncio

        pii = await asyncio.to_thread(detect_pii, query)
        redacted = redact_pii(query, pii) if pii else query
        findings: list[dict[str, Any]] = [
            {
                "category": "pii",
                "triggered": True,
                "reason": "Presidio detected personal information.",
                "confidence": item["confidence"],
                "start": item["start"],
                "end": item["end"],
                "entity_type": item["entity_type"],
            }
            for item in pii
        ]

        enabled_categories = tuple(
            category for category in INPUT_CATEGORIES
            if self._enabled(category, policy, output=False)
        )
        if enabled_categories and settings.JEV_ENABLED:
            semantic = await asyncio.to_thread(
                self.judge.classify,
                target=query,
                history=self._history_context(history, policy.history_window_exchanges),
                organization_policy=self._organization_policy_text(policy),
                categories=enabled_categories,
            )
            findings.extend(semantic.values())
        elif enabled_categories:
            logger.warning("JEV is disabled; semantic input classifications are unavailable.")

        topicality = {"decision": "not_configured", "similarity": None}
        if policy.topicality_enabled and policy.restricted_topics:
            try:
                restricted_similarity = await asyncio.to_thread(
                    self._embedding_similarity, query, policy.restricted_topics
                )
                if restricted_similarity >= policy.topicality_high_threshold:
                    findings.append({
                        "category": "organization_policy",
                        "triggered": True,
                        "reason": "The query closely matches an organization-restricted topic.",
                        "confidence": round(restricted_similarity, 4),
                    })
                    topicality = {
                        "decision": "off_topic",
                        "similarity": round(restricted_similarity, 4),
                    }
            except Exception:
                logger.exception("Restricted-topic similarity check failed.")
                topicality["decision"] = "uncertain"

        if (
            topicality["decision"] == "not_configured"
            and policy.topicality_enabled
            and policy.allowed_topics
        ):
            try:
                similarity = await asyncio.to_thread(
                    self._embedding_similarity, query, policy.allowed_topics
                )
                topicality["similarity"] = round(similarity, 4)
                if similarity >= policy.topicality_high_threshold:
                    topicality["decision"] = "on_topic"
                elif similarity < policy.topicality_low_threshold:
                    topicality["decision"] = "off_topic"
                elif settings.JEV_ENABLED:
                    topicality_result = await asyncio.to_thread(
                        self.judge.classify,
                        target=query,
                        history=self._history_context(history, policy.history_window_exchanges),
                        organization_policy=self._organization_policy_text(policy),
                        categories=("topicality",),
                    )
                    topicality["decision"] = (
                        "on_topic" if "topicality" in topicality_result else "off_topic"
                    )
                    if topicality_result:
                        findings.extend(topicality_result.values())
                else:
                    topicality["decision"] = "uncertain"
            except Exception:
                logger.exception("Topicality embedding failed; falling back to JEV.")
                if settings.JEV_ENABLED:
                    try:
                        topicality_result = await asyncio.to_thread(
                            self.judge.classify,
                            target=query,
                            history=self._history_context(history, policy.history_window_exchanges),
                            organization_policy=self._organization_policy_text(policy),
                            categories=("topicality",),
                        )
                        topicality["decision"] = (
                            "on_topic" if "topicality" in topicality_result else "off_topic"
                        )
                        if topicality_result:
                            findings.extend(topicality_result.values())
                    except Exception:
                        logger.exception("Topicality JEV fallback failed.")
                        topicality["decision"] = "uncertain"
                else:
                    topicality["decision"] = "uncertain"

        blocked = []
        for finding in findings:
            category = finding["category"]
            if category in {"pii", "topicality"}:
                continue  # PII has consent; topicality is a route decision, not a safety violation.
            if self._action(category, policy, output=False) != GuardrailAction.ALLOW:
                blocked.append(finding)

        logger.info(
            "Input guardrail decision: finding_categories=%s blocked=%s topicality=%s",
            sorted({item["category"] for item in findings}),
            bool(blocked),
            topicality["decision"],
        )
        return {
            "findings": findings,
            "pii_findings": pii,
            "redacted_query": redacted,
            "blocked_findings": blocked,
            "topicality": topicality,
        }

    async def inspect_output(
        self,
        *,
        answer: str,
        query: str,
        history: list[Any] | None,
        policy: EffectiveGuardrailPolicy,
        evidence: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        import asyncio

        pii = await asyncio.to_thread(detect_pii, answer)
        secrets = detect_secrets(answer)
        findings: list[dict[str, Any]] = []
        if self._enabled("pii_leakage", policy, output=True):
            findings.extend(
                {
                    "category": "pii_leakage",
                    "triggered": True,
                    "reason": "Presidio detected personal information in the generated answer.",
                    **item,
                }
                for item in pii
            )
        if self._enabled("secret_leakage", policy, output=True):
            findings.extend(
                {
                    "category": "secret_leakage",
                    "triggered": True,
                    "reason": "A credential or secret-like value was detected in the generated answer.",
                    **item,
                }
                for item in secrets
            )

        enabled_categories = tuple(
            category for category in OUTPUT_CATEGORIES
            if self._enabled(category, policy, output=True)
        )
        if enabled_categories and settings.JEV_ENABLED:
            semantic = await asyncio.to_thread(
                self.judge.classify,
                target=answer,
                history=self._history_context(history, policy.history_window_exchanges),
                organization_policy=(
                    self._organization_policy_text(policy, include_output=True)
                    + "\nOriginal user request (untrusted): " + query[:4000]
                ),
                evidence=self._serialize_evidence(evidence),
                categories=enabled_categories,
            )
            findings.extend(semantic.values())
        elif enabled_categories:
            logger.warning("JEV is disabled; semantic output classifications are unavailable.")

        blocked = [
            item for item in findings
            if self._action(item["category"], policy, output=True) != GuardrailAction.ALLOW
            and not (
                self._action(item["category"], policy, output=True) == GuardrailAction.REDACT
                and item.get("start") is not None and item.get("end") is not None
            )
        ]
        redactions = [
            item for item in findings
            if self._action(item["category"], policy, output=True) == GuardrailAction.REDACT
            and item.get("start") is not None and item.get("end") is not None
        ]
        transformed = answer
        if redactions:
            transformed = redact_pii(
                answer,
                [
                    {
                        "start": item["start"],
                        "end": item["end"],
                        "entity_type": item.get("entity_type") or item["category"].upper(),
                    }
                    for item in redactions
                ],
            )
            # Re-run deterministic leak detectors after transformation.
            if detect_pii(transformed) or detect_secrets(transformed):
                blocked.append({
                    "category": "transformation_recheck",
                    "triggered": True,
                    "reason": "Sensitive content remained after output transformation.",
                    "confidence": 1.0,
                })
            elif settings.JEV_ENABLED and enabled_categories:
                semantic_recheck = await asyncio.to_thread(
                    self.judge.classify,
                    target=transformed,
                    history=self._history_context(history, policy.history_window_exchanges),
                    organization_policy=(
                        self._organization_policy_text(policy, include_output=True)
                        + "\\nOriginal user request (untrusted): " + query[:4000]
                    ),
                    evidence=self._serialize_evidence(evidence),
                    categories=enabled_categories,
                )
                blocked.extend(
                    finding for finding in semantic_recheck.values()
                    if self._action(finding["category"], policy, output=True) != GuardrailAction.ALLOW
                )

        logger.info(
            "Output guardrail decision: finding_categories=%s blocked=%s",
            sorted({item["category"] for item in findings}),
            bool(blocked),
        )
        return {
            "findings": findings,
            "blocked_findings": blocked,
            "transformed_answer": transformed,
        }

    async def inspect_stream_segment(
        self,
        *,
        segment: str,
        query: str,
        history: list[Any] | None,
        policy: EffectiveGuardrailPolicy,
        evidence: list[dict[str, Any]] | None = None,
    ) -> str:
        """Inspect a complete buffered sentence before it is emitted to the client."""
        segment_policy = policy.model_copy(deep=True)
        # Grounding and whole-answer topicality need the complete response.
        segment_policy.output_enabled["grounding"] = False
        segment_policy.output_enabled["off_topic"] = False
        checked = await self.inspect_output(
            answer=segment,
            query=query,
            history=history,
            policy=segment_policy,
            evidence=evidence,
        )
        if checked["blocked_findings"]:
            raise GuardrailBlockedError(
                "A generated segment was stopped by output guardrails.",
                checked["blocked_findings"],
            )
        return checked["transformed_answer"]

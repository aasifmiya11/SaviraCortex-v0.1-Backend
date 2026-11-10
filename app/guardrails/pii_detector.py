from __future__ import annotations

from functools import lru_cache
from typing import Any

from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpArtifacts, NlpEngine


class _RegexOnlyNlpEngine(NlpEngine):
    """No-model NLP adapter: Presidio regex recognizers remain active without downloading spaCy."""

    def __init__(self) -> None:
        import spacy
        self._spacy = spacy

    def load(self) -> None:
        return None

    def is_loaded(self) -> bool:
        return True

    def process_text(self, text: str, language: str) -> NlpArtifacts:
        doc = self._spacy.blank(language if language in {"en"} else "en")(text)
        return NlpArtifacts(
            entities=[],
            tokens=doc,
            tokens_indices=[token.idx for token in doc],
            lemmas=[token.lemma_ or token.text.lower() for token in doc],
            nlp_engine=self,
            language=language,
        )

    def process_batch(self, texts, language, batch_size=1, n_process=1, **kwargs):
        for text in texts:
            yield text, self.process_text(text, language)

    def is_stopword(self, word: str, language: str) -> bool:
        return False

    def is_punct(self, word: str, language: str) -> bool:
        return bool(word) and all(not char.isalnum() for char in word)

    def get_supported_entities(self) -> list[str]:
        return []

    def get_supported_languages(self) -> list[str]:
        return ["en"]


@lru_cache(maxsize=1)
def _analyzer() -> AnalyzerEngine:
    return AnalyzerEngine(nlp_engine=_RegexOnlyNlpEngine(), supported_languages=["en"])


def detect_pii(text: str) -> list[dict[str, Any]]:
    """Return Presidio detections with source offsets; raw values are never returned."""
    if not text:
        return []
    results = _analyzer().analyze(text=text, language="en")
    candidates = [
        {
            "entity_type": item.entity_type,
            "start": item.start,
            "end": item.end,
            "confidence": round(float(item.score), 4),
        }
        for item in results
    ]
    # Presidio may emit overlapping generic recognitions (for example URL
    # inside EMAIL_ADDRESS). Keep the strongest span to make redaction stable.
    accepted: list[dict[str, Any]] = []
    for item in sorted(
        candidates,
        key=lambda value: (
            -value["confidence"],
            -(value["end"] - value["start"]),
            value["start"],
        ),
    ):
        if any(
            item["start"] < current["end"] and current["start"] < item["end"]
            for current in accepted
        ):
            continue
        accepted.append(item)
    return sorted(accepted, key=lambda value: value["start"])


def redact_pii(text: str, findings: list[dict[str, Any]]) -> str:
    """Replace detected spans from right to left so offsets remain valid."""
    redacted = text
    accepted: list[dict[str, Any]] = []
    for item in sorted(
        findings,
        key=lambda value: (
            -float(value.get("confidence", 1.0)),
            -(int(value["end"]) - int(value["start"])),
            int(value["start"]),
        ),
    ):
        if any(
            int(item["start"]) < int(current["end"])
            and int(current["start"]) < int(item["end"])
            for current in accepted
        ):
            continue
        accepted.append(item)
    for item in sorted(accepted, key=lambda result: result["start"], reverse=True):
        start, end = int(item["start"]), int(item["end"])
        entity = str(item.get("entity_type") or "PERSONAL_DATA")
        redacted = redacted[:start] + f"[REDACTED_{entity}]" + redacted[end:]
    return redacted

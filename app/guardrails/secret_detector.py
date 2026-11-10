from __future__ import annotations

import re
from typing import Any

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("PRIVATE_KEY", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("AWS_ACCESS_KEY", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GITHUB_TOKEN", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
    ("GENERIC_API_KEY", re.compile(r"\b(?:sk|rk|pk|api)[-_][A-Za-z0-9_-]{24,}\b", re.I)),
    ("BEARER_TOKEN", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{20,}={0,2}", re.I)),
    ("PASSWORD_ASSIGNMENT", re.compile(r"\b(?:password|passwd|secret)\s*[:=]\s*[^\s,;]{8,}", re.I)),
)


def detect_secrets(text: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for entity_type, pattern in _PATTERNS:
        for match in pattern.finditer(text or ""):
            findings.append({
                "entity_type": entity_type,
                "start": match.start(),
                "end": match.end(),
                "confidence": 0.99,
            })
    return findings

"""Secret redaction before LLM extraction or persistence."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import SecretDetectedError


@dataclass(frozen=True)
class RedactionResult:
    content: str
    findings: list[str]


PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S)),
]


def redact_secrets(content: str, *, strict: bool = False) -> RedactionResult:
    """Replace recognized secrets and optionally reject the payload."""

    findings: list[str] = []
    redacted = content
    for label, pattern in PATTERNS:
        if pattern.search(redacted):
            findings.append(label)
            redacted = pattern.sub(f"[REDACTED:{label}]", redacted)
    if strict and findings:
        raise SecretDetectedError(f"secret-like content detected: {', '.join(findings)}")
    return RedactionResult(content=redacted, findings=findings)


"""Named failures for every externally visible brain path."""

from __future__ import annotations


class BrainError(Exception):
    """Base class for expected Open Brain failures."""


class InvalidEnvelopeError(BrainError):
    """Raised when an ingest envelope is missing required shape."""


class EmptyContentError(BrainError):
    """Raised when input content is empty after normalization."""


class PayloadTooLargeError(BrainError):
    """Raised when input content exceeds the configured size limit."""


class SecretDetectedError(BrainError):
    """Raised when strict secret policy rejects redacted content."""


class DuplicateEventError(BrainError):
    """Raised when an idempotency key already exists and duplicate mode is strict."""


class StoreWriteError(BrainError):
    """Raised when SQLite cannot persist a required write."""


class StoreReadError(BrainError):
    """Raised when SQLite cannot satisfy a read."""


class LlmExtractionError(BrainError):
    """Raised when the LLM extractor fails after the raw event was stored."""


class SkillProposalNotFoundError(BrainError):
    """Raised when a skill proposal id does not exist."""


class SkillPatchUnsafeError(BrainError):
    """Raised when a skill patch targets a path outside the allowed root."""


class SkillPatchConflictError(BrainError):
    """Raised when a proposal cannot be applied to the current file contents."""


class SkillPatchTestError(BrainError):
    """Raised when applying a skill proposal fails verification tests."""


class SlackSignatureError(BrainError):
    """Raised when a Slack request signature is missing or invalid."""


class GitHubIngestError(BrainError):
    """Raised when GitHub data cannot be fetched or normalized."""


class SyncAuthError(BrainError):
    """Raised when a sync peer request has invalid authentication."""


class SyncConflictError(BrainError):
    """Raised when sync detects incompatible peer state."""


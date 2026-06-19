"""LLM provider configuration and chat clients for Noggin Workers."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from .config import load_user_env
from .errors import LlmConfigurationError, LlmExtractionError


class LlmClient(Protocol):
    """Small chat interface used by Noggin Workers."""

    provider: str
    model: str

    def complete_json(self, messages: list[dict[str, str]], *, timeout: float | None = None) -> object:
        """Return parsed JSON from an LLM response."""


@dataclass(frozen=True)
class ProviderConfig:
    """Resolved provider settings.

    Noggin is intentionally LLM-only. Production clients require an API key even
    when the downstream provider can run without one; that keeps deployment
    behavior explicit and avoids silently switching to local fallback logic.
    """

    provider: str
    api_key: str
    model: str
    base_url: str
    timeout: float = 45.0
    temperature: float = 0.2

    @classmethod
    def from_env(cls) -> "ProviderConfig":
        load_user_env()
        provider = os.getenv("NOGGIN_PROVIDER", "openai").strip().lower()
        api_key = (
            os.getenv("NOGGIN_API_KEY")
            or os.getenv(f"NOGGIN_{provider.upper()}_API_KEY")
            or _legacy_provider_key(provider)
            or ""
        ).strip()
        if not api_key:
            raise LlmConfigurationError(
                "Noggin requires an LLM API key. Set NOGGIN_API_KEY or "
                f"NOGGIN_{provider.upper()}_API_KEY."
            )

        defaults = _provider_defaults(provider)
        model = os.getenv("NOGGIN_MODEL", defaults["model"]).strip()
        base_url = os.getenv("NOGGIN_BASE_URL", defaults["base_url"]).strip().rstrip("/")
        timeout = float(os.getenv("NOGGIN_LLM_TIMEOUT", "45"))
        temperature = float(os.getenv("NOGGIN_TEMPERATURE", "0.2"))
        return cls(
            provider=provider,
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout=timeout,
            temperature=temperature,
        )


class OpenAIStyleClient:
    """Client for OpenAI-compatible chat-completions APIs."""

    def __init__(self, config: ProviderConfig):
        self.config = config
        self.provider = config.provider
        self.model = config.model

    def complete_json(self, messages: list[dict[str, str]], *, timeout: float | None = None) -> object:
        payload = {
            "model": self.model,
            "temperature": self.config.temperature,
            "messages": messages,
            "response_format": {"type": "json_object"},
        }
        raw = self._post_json("/chat/completions", payload, timeout=timeout)
        try:
            text = raw["choices"][0]["message"]["content"]
            return json.loads(_strip_json_fence(str(text)))
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise LlmExtractionError(f"{self.provider} returned invalid JSON content") from exc

    def _post_json(self, path: str, payload: dict[str, object], *, timeout: float | None) -> object:
        request = urllib.request.Request(
            self.config.base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "noggin/0.1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.config.timeout) as response:  # noqa: S310
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise LlmExtractionError(f"{self.provider} LLM request failed: {exc}") from exc


class AnthropicClient:
    """Client for Anthropic Messages API."""

    provider = "anthropic"

    def __init__(self, config: ProviderConfig):
        self.config = config
        self.model = config.model

    def complete_json(self, messages: list[dict[str, str]], *, timeout: float | None = None) -> object:
        system = "\n\n".join(msg["content"] for msg in messages if msg["role"] == "system")
        user_messages = [msg for msg in messages if msg["role"] != "system"]
        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "temperature": self.config.temperature,
            "system": system,
            "messages": user_messages,
        }
        request = urllib.request.Request(
            self.config.base_url + "/messages",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "x-api-key": self.config.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
                "User-Agent": "noggin/0.1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.config.timeout) as response:  # noqa: S310
                raw = json.loads(response.read().decode("utf-8"))
            text = "".join(block.get("text", "") for block in raw.get("content", []))
            return json.loads(_strip_json_fence(text))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, AttributeError) as exc:
            raise LlmExtractionError(f"anthropic LLM request failed: {exc}") from exc


class GeminiClient:
    """Client for Google Gemini generateContent API."""

    provider = "gemini"

    def __init__(self, config: ProviderConfig):
        self.config = config
        self.model = config.model

    def complete_json(self, messages: list[dict[str, str]], *, timeout: float | None = None) -> object:
        prompt = "\n\n".join(f"{msg['role'].upper()}: {msg['content']}" for msg in messages)
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": self.config.temperature,
                "responseMimeType": "application/json",
            },
        }
        url = f"{self.config.base_url}/models/{self.model}:generateContent?key={self.config.api_key}"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "noggin/0.1.0"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.config.timeout) as response:  # noqa: S310
                raw = json.loads(response.read().decode("utf-8"))
            text = raw["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(_strip_json_fence(str(text)))
        except (urllib.error.URLError, TimeoutError, KeyError, IndexError, json.JSONDecodeError) as exc:
            raise LlmExtractionError(f"gemini LLM request failed: {exc}") from exc


def make_llm_client(config: ProviderConfig | None = None) -> LlmClient:
    """Return a provider-specific LLM client."""

    resolved = config or ProviderConfig.from_env()
    if resolved.provider == "anthropic":
        return AnthropicClient(resolved)
    if resolved.provider == "gemini":
        return GeminiClient(resolved)
    if resolved.provider in {"openai", "openrouter", "groq", "together", "mistral", "ollama", "custom"}:
        return OpenAIStyleClient(resolved)
    raise LlmConfigurationError(f"unsupported NOGGIN_PROVIDER: {resolved.provider}")


def _provider_defaults(provider: str) -> dict[str, str]:
    defaults = {
        "openai": {"model": "gpt-4o-mini", "base_url": "https://api.openai.com/v1"},
        "openrouter": {"model": "openai/gpt-4o-mini", "base_url": "https://openrouter.ai/api/v1"},
        "anthropic": {"model": "claude-3-5-haiku-latest", "base_url": "https://api.anthropic.com/v1"},
        "gemini": {
            "model": "gemini-1.5-flash",
            "base_url": "https://generativelanguage.googleapis.com/v1beta",
        },
        "groq": {"model": "llama-3.1-8b-instant", "base_url": "https://api.groq.com/openai/v1"},
        "together": {
            "model": "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
            "base_url": "https://api.together.xyz/v1",
        },
        "mistral": {"model": "mistral-small-latest", "base_url": "https://api.mistral.ai/v1"},
        "ollama": {"model": "llama3.1", "base_url": "http://127.0.0.1:11434/v1"},
        "custom": {"model": "model", "base_url": "http://127.0.0.1:8000/v1"},
    }
    if provider not in defaults:
        raise LlmConfigurationError(f"unsupported NOGGIN_PROVIDER: {provider}")
    return defaults[provider]


def _legacy_provider_key(provider: str) -> str:
    if provider == "openai":
        return os.getenv("OPENAI_API_KEY", "")
    if provider == "anthropic":
        return os.getenv("ANTHROPIC_API_KEY", "")
    if provider == "gemini":
        return os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
    return ""


def _strip_json_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:]
    return stripped.strip()

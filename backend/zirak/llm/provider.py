"""LLM provider abstraction (OpenAI-compatible chat completions) plus a mock.

The LLM only analyses, proposes and explains. Every caller has a deterministic fallback, so with
MOCK_LLM=true (or when the LLM is down) the whole app still works.
"""

from __future__ import annotations

from typing import Protocol

import httpx

from zirak.config import Settings


class LLMProvider(Protocol):
    name: str

    async def chat(self, system: str, user: str, json_mode: bool = False) -> str | None:
        """Return the model's text, or None when the caller should use its deterministic fallback."""
        ...


class MockLLM:
    """Returns None so every feature uses its built-in deterministic (template / rule-based) answer."""

    name = "mock"

    async def chat(self, system: str, user: str, json_mode: bool = False) -> str | None:
        return None


class OpenAICompatLLM:
    name = "openai-compatible"

    def __init__(self, base_url: str, api_key: str, model: str, timeout_s: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_s = timeout_s

    async def chat(self, system: str, user: str, json_mode: bool = False) -> str | None:
        body: dict[str, object] = {
            "model": self.model,
            "temperature": 0.2,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                r = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=body,
                )
                r.raise_for_status()
                content = r.json()["choices"][0]["message"]["content"]
                return str(content) if content else None
        except (httpx.HTTPError, KeyError, IndexError, ValueError):
            return None


def build_llm(settings: Settings) -> LLMProvider:
    if settings.mock_llm or not (settings.llm_base_url and settings.llm_api_key and settings.llm_model):
        return MockLLM()
    return OpenAICompatLLM(
        settings.llm_base_url, settings.llm_api_key, settings.llm_model, settings.llm_timeout_s
    )

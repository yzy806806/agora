"""LLM Client for Agora discussion driving.

Reads AGORA_LLM_* environment variables and calls an OpenAI-compatible
chat completions API.  Supports per-role model overrides via
AGORA_LLM_ROLE_MODEL_{ARCHITECT,DEVELOPER,REVIEWER}.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class LLMConfig:
    """LLM configuration read from AGORA_LLM_* env vars."""

    base_url: str = ""
    api_key: str = ""
    model: str = "gpt-4o"
    max_tokens: int = 1024
    temperature: float = 0.3
    role_models: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> LLMConfig:
        """Build LLMConfig from AGORA_LLM_* environment variables."""
        role_models: dict[str, str] = {}
        for role_key, role_name in [
            ("ARCHITECT", "architect"),
            ("DEVELOPER", "developer"),
            ("REVIEWER", "reviewer"),
        ]:
            val = os.environ.get(f"AGORA_LLM_ROLE_MODEL_{role_key}", "")
            if val:
                role_models[role_name] = val

        return cls(
            base_url=os.environ.get("AGORA_LLM_BASE_URL", ""),
            api_key=os.environ.get("AGORA_LLM_API_KEY", ""),
            model=os.environ.get("AGORA_LLM_MODEL", "gpt-4o"),
            max_tokens=int(os.environ.get("AGORA_LLM_MAX_TOKENS", "1024")),
            temperature=float(os.environ.get("AGORA_LLM_TEMPERATURE", "0.3")),
            role_models=role_models,
        )


class LLMClient:
    """Async client for OpenAI-compatible chat completions API."""

    def __init__(self, config: LLMConfig | None = None) -> None:
        self.config = config or LLMConfig.from_env()
        self._client: httpx.AsyncClient | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.config.base_url,
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(60.0, connect=10.0),
            )
        return self._client

    def _resolve_model(self, role: str) -> str:
        """Return the model to use for a given role.

        Falls back to the default model if no role-specific override.
        """
        return self.config.role_models.get(role, self.config.model)

    async def chat(
        self,
        role: str,
        system_prompt: str,
        messages: list[dict[str, str]],
    ) -> str:
        """Send a chat completion request and return the assistant reply.

        Args:
            role: Discussion role (architect/developer/reviewer) — used to
                  select the per-role model override.
            system_prompt: System message injected at the start.
            messages: Conversation history as ``[{"role": ..., "content": ...}]``.

        Returns:
            The assistant's reply text.

        Raises:
            RuntimeError: If all retries are exhausted.
        """
        model = self._resolve_model(role)
        full_messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
        ] + messages

        payload: dict[str, Any] = {
            "model": model,
            "messages": full_messages,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
        }

        last_exc: Exception | None = None
        for attempt in range(3):  # initial + 2 retries
            try:
                client = await self._ensure_client()
                resp = await client.post("/chat/completions", json=payload)
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                logger.debug(
                    "LLM response for role=%s model=%s len=%d attempt=%d",
                    role, model, len(content), attempt + 1,
                )
                return content
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "LLM call failed (attempt %d/3) role=%s model=%s: %s",
                    attempt + 1, role, model, exc,
                )
                if attempt < 2:
                    # Brief back-off before retry
                    import asyncio
                    await asyncio.sleep(1.0 * (attempt + 1))

        raise RuntimeError(
            f"LLM call failed after 3 attempts for role={role} model={model}: "
            f"{last_exc}"
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> LLMClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

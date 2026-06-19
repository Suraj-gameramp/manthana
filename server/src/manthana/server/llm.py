"""Server-side LLM provider abstraction.

Open item (tracked in manthana-decisions.md / architecture §9): the server has no
engineer's Claude account, so the founder-query narrative needs its own provider.
Dev/tests use the deterministic ``ScriptedProvider``/``MockProvider``; v1.5 the
org provisions a server API key behind this same interface. Kept server-local
(not imported from the agent) so the AGPL server stays decoupled from the local
agent + collectors.

SPDX-License-Identifier: AGPL-3.0-or-later
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .config import ServerConfig


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    def complete(self, prompt: str) -> str:
        """Return the model's result text for a prompt."""
        ...


class MockProvider:
    """Always returns the same response (single-call use)."""

    name = "mock"

    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[str] = []

    def complete(self, prompt: str) -> str:
        self.calls.append(prompt)
        return self.response


class ScriptedProvider:
    """Returns queued responses in order (multi-call pipelines, e.g. founder query)."""

    name = "scripted"

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[str] = []

    def complete(self, prompt: str) -> str:
        self.calls.append(prompt)
        if not self._responses:
            return ""
        return self._responses.pop(0)


class AnthropicProvider:
    """Real server-side provider — the Anthropic Messages API (arch §9).

    The org provisions ``ANTHROPIC_API_KEY``; the SDK ships as the optional
    ``manthana-server[llm]`` extra so dev/tests (which use the mock) stay
    dependency-free. Tests inject a fake ``client`` to avoid any network/key.
    """

    name = "anthropic"

    def __init__(
        self,
        *,
        model: str,
        max_tokens: int = 1024,
        api_key: str | None = None,
        client: Any = None,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        if client is not None:
            self._client = client
            return
        try:
            from anthropic import Anthropic  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - exercised only without the extra
            raise RuntimeError(
                "AnthropicProvider requires the 'anthropic' SDK — "
                "install the extra: pip install 'manthana-server[llm]'"
            ) from exc
        # Anthropic() reads ANTHROPIC_API_KEY from the environment when api_key is None.
        self._client = Anthropic(api_key=api_key) if api_key else Anthropic()

    def complete(self, prompt: str) -> str:
        message = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        # Concatenate only text blocks (tool-use / thinking blocks have no .text);
        # getattr-default guards a malformed text block missing .text.
        parts = [
            getattr(block, "text", "")
            for block in message.content
            if getattr(block, "type", None) == "text"
        ]
        return "".join(parts).strip()


def make_provider(config: ServerConfig) -> LLMProvider:
    """Select the founder-narrative provider from config (arch §9).

    Defaults to the deterministic mock so dev/tests need no API key; the org
    flips ``MANTHANA_SERVER_LLM=anthropic`` for a real, citation-grounded model.
    """
    if config.llm_provider == "anthropic":
        return AnthropicProvider(model=config.llm_model, max_tokens=config.llm_max_tokens)
    return MockProvider("{}")


__all__ = ["LLMProvider", "MockProvider", "ScriptedProvider", "AnthropicProvider", "make_provider"]

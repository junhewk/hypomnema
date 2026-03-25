"""LLM client protocol."""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LLMClient(Protocol):
    async def complete(self, prompt: str, *, system: str = "") -> str: ...
    async def complete_json(self, prompt: str, *, system: str = "") -> dict[str, Any]: ...

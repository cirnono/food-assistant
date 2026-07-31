from __future__ import annotations

from typing import Any, Protocol


class StructuredChatProvider(Protocol):
    async def structured_chat(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_schema: dict[str, Any],
    ) -> dict[str, Any]: ...

    async def unload(self) -> dict[str, Any]: ...

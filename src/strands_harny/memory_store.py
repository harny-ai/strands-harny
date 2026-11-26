"""A Strands ``MemoryStore`` backed by Harny's per-user memory API."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from harny import HarnyClient
from strands.memory import AddMessagesContext, MemoryEntry, MemoryStore, MemoryStoreConfig, SearchOptions
from strands.types.content import Message
from typing_extensions import Required, Unpack

logger = logging.getLogger("strands_harny")

_DEFAULT_NAME = "harny"
_DEFAULT_DESCRIPTION = "What this person told the app in past conversations, with the date each fact happened."


class HarnyMemoryStoreConfig(MemoryStoreConfig, total=False):
    """Constructor arguments of a ``HarnyMemoryStore``.

    Extends ``MemoryStoreConfig`` (name, description, max_search_results, writable, extraction).

    Attributes:
        user: Your own id for the person. The API reads and writes only that person's memory.
        level: How much evidence to recall: ``low``, ``medium``, ``high`` or ``extra-high``.
        api_key: App key (``fsa_``). Defaults to the ``HARNY_API_KEY`` environment variable.
        base_url: Harny API base URL. Defaults to ``HARNY_API_URL``, else ``https://api.harny.ai``.
        client: Your own ``harny.HarnyClient`` (a test double or a shared client); never closed by the store.
    """

    user: Required[str]
    level: str
    api_key: str
    base_url: str
    client: Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _fact_id(user: str, text: str) -> str:
    """A stable id for a saved fact: saying the same thing twice replaces nothing and costs nothing."""
    return hashlib.sha256(f"{user}\n{text}".encode("utf-8")).hexdigest()


def _day(value: Any) -> str:
    return str(value)[:10] if value else ""


def _text_of(message: Message) -> str:
    """The plain text of one Strands message (its ``text`` content blocks, joined)."""
    parts = [str(block["text"]) for block in message.get("content", []) if isinstance(block, dict) and "text" in block]
    return "\n".join(part for part in parts if part.strip()).strip()


class HarnyMemoryStore(MemoryStore):
    """Per-person long-term memory for a Strands agent.

    Search recalls dated facts for the person; ``add`` saves one fact; ``add_messages`` saves what the person
    said (user turns only, never the model's replies) so Harny can extract facts on the server.

    Example:
        ```python
        from strands import Agent
        from strands.memory import MemoryManager
        from strands_harny import HarnyMemoryStore

        store = HarnyMemoryStore(user="nadia")  # reads HARNY_API_KEY; "nadia" is YOUR id for the person
        agent = Agent(memory_manager=MemoryManager(stores=[store]))
        ```
    """

    def __init__(self, **store_config: Unpack[HarnyMemoryStoreConfig]) -> None:
        """Initialize the store. Needs ``user``; the key is read from ``HARNY_API_KEY`` unless given."""
        user = str(store_config.get("user") or "").strip()
        if not user:
            raise ValueError("HarnyMemoryStore needs user: your own id for the person whose memory this is")
        self.user = user
        self.name = store_config.get("name", _DEFAULT_NAME)
        self.description = store_config.get("description", _DEFAULT_DESCRIPTION)
        self.max_search_results = store_config.get("max_search_results")
        self.writable = store_config.get("writable", True)
        self.extraction = store_config.get("extraction")
        self.level = store_config.get("level", "medium")
        client = store_config.get("client")
        self._owns_client = client is None
        self._client = (
            client
            if client is not None
            else HarnyClient(api_key=store_config.get("api_key"), base_url=store_config.get("base_url"))
        )

    async def close(self) -> None:
        """Close the HTTP client the store created. A client you passed in is left open."""
        if self._owns_client:
            await self._client.close()

    async def search(self, query: str, options: SearchOptions | None = None) -> list[MemoryEntry]:
        """Recall dated facts for the person, newest answer first when a fact changed. A memory problem returns []."""
        limit = (options or {}).get("max_search_results") or self.max_search_results
        try:
            answer = await self._client.recall(query, level=self.level, limit=limit, user=self.user)
        except Exception as exc:  # a memory problem never fails the agent run
            logger.warning("harny recall failed: %s", getattr(exc, "error_code", None) or type(exc).__name__)
            return []
        pending = answer.pending.message if answer.pending else None
        entries = []
        for result in answer.results:
            if not result.content.strip():
                continue
            metadata: dict[str, Any] = {
                "id": result.id,
                "rank": result.rank,
                "occurred_at": result.occurredAt,
                "sources": [{"source_id": s.sourceId, "label": s.label} for s in result.sources],
            }
            if pending:
                metadata["pending"] = pending
            when = _day(result.occurredAt)
            content = f"({when}) {result.content}" if when else result.content
            entries.append(MemoryEntry(content=content, metadata=metadata))
        return entries

    async def add(self, content: str, metadata: dict[str, Any] | None = None) -> Any:
        """Save one fact for the person. The same words again are the same fact and cost nothing."""
        label = str((metadata or {}).get("label") or "") or None
        return await self._client.ingest_data_point(
            content, id=_fact_id(self.user, content), label=label, timestamp=_now_iso(), user=self.user
        )

    async def add_messages(self, messages: list[Message], context: AddMessagesContext | None = None) -> Any:
        """Save what the person said, so Harny extracts facts on the server. Only ``user`` turns are sent."""
        receipts = []
        for message in messages:
            if message.get("role") != "user":
                continue
            text = _text_of(message)
            if text:
                receipts.append(await self.add(text, {"label": "Conversation message"}))
        return receipts

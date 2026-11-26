"""Tests for HarnyMemoryStore: a fake client, the real SDK over a mock transport, and a MemoryManager."""

import pytest
from harny import HarnyAPIError
from strands.memory import MemoryManager

from strands_harny import HarnyMemoryStore
from tests.conftest import FakeClient


def make(client, **kwargs):
    return HarnyMemoryStore(user="nadia", client=client, **kwargs)


def test_needs_a_user(fake):
    with pytest.raises(ValueError):
        HarnyMemoryStore(user="  ", client=fake)


def test_defaults(fake):
    store = make(fake)
    assert (store.name, store.writable, store.level, store.user) == ("harny", True, "medium", "nadia")
    assert make(fake, name="notes", writable=False).writable is False


async def test_search_returns_dated_entries_in_rank_order(fake):
    entries = await make(fake).search("What is the Acme pilot budget?")
    assert [e.content for e in entries] == [
        "(2026-03-01) Acme pilot budget: currently 40k.",
        "(2026-02-03) Acme pilot ships March 14.",
    ]
    assert entries[0].metadata["rank"] == 1
    assert entries[0].metadata["sources"] == [{"source_id": "call-8821", "label": "Budget change"}]
    assert fake.calls[0][2] == {"level": "medium", "limit": None, "user": "nadia"}


async def test_search_passes_the_result_limit(fake):
    await make(fake, max_search_results=3).search("q")
    assert fake.calls[0][2]["limit"] == 3
    await make(fake, max_search_results=3).search("q", {"max_search_results": 7})
    assert fake.calls[1][2]["limit"] == 7


async def test_search_notes_facts_still_processing():
    answer = {
        "results": [{"id": "m", "rank": 1, "content": "A fact."}],
        "pending": {"ingestions": 1, "message": "Still processing."},
    }
    entries = await make(FakeClient(recall=answer)).search("q")
    assert entries[0].metadata["pending"] == "Still processing."
    assert entries[0].content == "A fact."


async def test_a_memory_problem_never_fails_the_run(caplog):
    err = HarnyAPIError("down", status_code=503, error_code="provider-down")
    assert await make(FakeClient(fail=err)).search("q") == []
    assert "provider-down" in caplog.text and "down" not in caplog.text.replace("provider-down", "")


async def test_add_saves_one_fact_with_a_stable_id(fake):
    store = make(fake)
    await store.add("Nadia raised the Acme pilot budget from 32k to 40k.", {"label": "Budget change"})
    await store.add("Nadia raised the Acme pilot budget from 32k to 40k.")
    first, second = fake.calls[0][2], fake.calls[1][2]
    assert first["id"] == second["id"] and len(first["id"]) == 64
    assert first["label"] == "Budget change" and second["label"] is None
    assert first["user"] == "nadia" and first["timestamp"].endswith("Z")


async def test_the_id_depends_on_the_person():
    a, b = FakeClient(), FakeClient()
    await HarnyMemoryStore(user="nadia", client=a).add("same words")
    await HarnyMemoryStore(user="omar", client=b).add("same words")
    assert a.calls[0][2]["id"] != b.calls[0][2]["id"]


async def test_add_messages_sends_user_turns_only(fake):
    messages = [
        {"role": "user", "content": [{"text": "My daughter starts school on 3 March."}]},
        {"role": "assistant", "content": [{"text": "Noted, I will remember that."}]},
        {"role": "user", "content": [{"text": "   "}]},
        {"role": "user", "content": [{"text": "I prefer email."}, {"toolUse": {"name": "x"}}]},
    ]
    receipts = await make(fake).add_messages(messages)
    assert [c[1] for c in fake.calls] == ["My daughter starts school on 3 March.", "I prefer email."]
    assert len(receipts) == 2


async def test_close_only_closes_a_client_the_store_made(fake):
    store = make(fake)
    await store.close()
    assert fake.closed is False


async def test_the_real_sdk_sends_the_expected_requests(wire):
    store = HarnyMemoryStore(user="nadia", client=wire, max_search_results=5)
    entries = await store.search("What is the Acme pilot budget?")
    await store.add("Nadia prefers email.")
    recall, ingest = wire.seen
    assert recall["path"].endswith("/memory/recall") and recall["user"] == "nadia"
    assert recall["body"] == {
        "query": "What is the Acme pilot budget?",
        "identity": "nadia",
        "level": "medium",
        "limit": 5,
    }
    assert ingest["path"].endswith("/memory/ingest") and ingest["user"] == "nadia"
    assert ingest["body"]["content"] == "Nadia prefers email." and len(ingest["body"]["id"]) == 64
    assert entries[0].metadata["id"] == "m1"


async def test_inside_a_memory_manager(fake):
    manager = MemoryManager(stores=[make(fake)])
    found = await manager.search("What is the Acme pilot budget?")
    assert found[0].store_name == "harny" and "40k" in found[0].content
    await manager.add("Nadia prefers email.")
    assert [c[0] for c in fake.calls] == ["recall", "ingest"]


def test_a_writable_store_needs_a_write_sink_so_the_manager_accepts_it(fake):
    MemoryManager(stores=[make(fake)], add_tool_config=True)

"""Shared test doubles. No test calls the network: the SDK is driven through httpx's MockTransport."""

import json

import httpx
import pytest
from harny import HarnyClient
from harny._memory_v1 import MemoryIngestReceipt, MemoryRecall

RECALL = {
    "asOf": "2026-03-02T00:00:00Z",
    "usedEvidenceTokens": 40,
    "results": [
        {
            "id": "m1",
            "rank": 1,
            "occurredAt": "2026-03-01T09:00:00Z",
            "content": "Acme pilot budget: currently 40k.",
            "sources": [{"sourceId": "call-8821", "label": "Budget change", "excerpts": []}],
        },
        {
            "id": "m2",
            "rank": 2,
            "occurredAt": "2026-02-03T09:00:00Z",
            "content": "Acme pilot ships March 14.",
            "sources": [],
        },
    ],
}


class FakeClient:
    """Stands in for ``harny.HarnyClient``: records calls, answers from memory."""

    def __init__(self, recall=None, fail=None):
        self.calls = []
        self._recall = recall if recall is not None else RECALL
        self._fail = fail
        self.closed = False

    async def recall(self, query, **kwargs):
        self.calls.append(("recall", query, kwargs))
        if self._fail:
            raise self._fail
        return MemoryRecall.model_validate(self._recall)

    async def ingest_data_point(self, content, **kwargs):
        self.calls.append(("ingest", content, kwargs))
        return MemoryIngestReceipt(ingestionId="ing-1", sourceId=kwargs.get("id"), status="processing")

    async def close(self):
        self.closed = True


@pytest.fixture
def fake():
    return FakeClient()


@pytest.fixture
def wire():
    """A real ``harny.HarnyClient`` whose HTTP layer is a MockTransport. ``wire.seen`` lists the requests."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            {
                "method": request.method,
                "path": request.url.path,
                "user": request.headers.get("x-harny-user"),
                "body": json.loads(request.content or b"{}"),
            }
        )
        if request.url.path.endswith("/memory/recall"):
            return httpx.Response(200, json=RECALL)
        return httpx.Response(
            202, json={"ingestionId": "ing-1", "sourceId": seen[-1]["body"].get("id"), "status": "processing"}
        )

    client = HarnyClient(api_key="fsa_test_key_not_real", base_url="https://harny.invalid")
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://harny.invalid/v1")
    client._get_http = lambda: http  # type: ignore[method-assign]
    client.seen = seen  # type: ignore[attr-defined]
    return client

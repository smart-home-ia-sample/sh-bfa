"""Builds the BFA's capability catalog by **pulling** each source's descriptor —
no self-registration. A source is either an A2A agent (serves an agent card at
`/.well-known/agent-card.json`) or the MCP server (serves `/tools`); the BFA
probes for which. See `spec/13-catalog-first-discovery`.

`CATALOG_SOURCES` env: comma/newline-separated base URLs, e.g.
    http://security:8200,http://environment:8300,http://home-mcp:8100
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

import httpx

from app.models import CatalogItem
from app.search import SearchIndex

DEFAULT_TIMEOUT = 5.0
AGENT_CARD_PATH = "/.well-known/agent-card.json"
MCP_TOOLS_PATH = "/tools"


def _new_client() -> httpx.Client:
    """Seam for tests to inject an httpx.MockTransport."""
    return httpx.Client(timeout=DEFAULT_TIMEOUT)


def sources() -> list[str]:
    raw = os.environ.get("CATALOG_SOURCES", "")
    return [u.strip().rstrip("/") for u in raw.replace("\n", ",").split(",") if u.strip()]


def _service_name(url: str) -> str:
    return urlparse(url).hostname or url


def _agent_items(card: dict) -> list[CatalogItem]:
    return [
        CatalogItem(
            id=s.get("id", ""),
            name=s.get("name", ""),
            description=s.get("description", "") or "",
            tags=s.get("tags") or [],
            examples=s.get("examples") or [],
        )
        for s in card.get("skills", [])
    ]


def _tool_items(payload: dict) -> list[CatalogItem]:
    items = []
    for t in payload.get("tools", []):
        ann = t.get("annotations") or {}
        items.append(
            CatalogItem(
                id=t.get("name", ""),
                name=t.get("name", ""),
                description=t.get("description", "") or "",
                tags=ann.get("tags") or [],
                examples=ann.get("examples") or [],
            )
        )
    return items


def _probe(client: httpx.Client, url: str) -> tuple[str, list[CatalogItem]]:
    """(kind, items) for a source. Tries the agent card first, then MCP tools."""
    card = client.get(f"{url}{AGENT_CARD_PATH}")
    if card.status_code == 200:
        return "agent", _agent_items(card.json())
    tools = client.get(f"{url}{MCP_TOOLS_PATH}")
    if tools.status_code == 200:
        return "tool", _tool_items(tools.json())
    raise RuntimeError(f"no agent card or /tools at {url} (card {card.status_code}, tools {tools.status_code})")


def build(index: SearchIndex, srcs: list[str] | None = None, client: httpx.Client | None = None) -> dict:
    """(Re)build `index` from the sources. Best-effort: a source that can't be
    reached is recorded in `errors` and skipped, not fatal. Entries for sources
    that dropped out of the list are pruned."""
    srcs = sources() if srcs is None else srcs
    owns_client = client is None
    client = client or _new_client()
    errors: list[dict] = []
    seen: set[tuple[str, str]] = set()
    try:
        for url in srcs:
            try:
                kind, items = _probe(client, url)
            except Exception as exc:  # noqa: BLE001 - any transport/parse failure is non-fatal
                errors.append({"source": url, "error": str(exc)})
                continue
            service = _service_name(url)
            index.set_source(kind, service, url, items)
            seen.add((kind, service))
    finally:
        if owns_client:
            client.close()
    index.retain(seen)
    return {"sources": srcs, "indexed": index.size(), "errors": errors}

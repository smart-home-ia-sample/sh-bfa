import httpx
import pytest
from fastapi.testclient import TestClient

from app import catalog
from app.main import app
from app.models import CatalogItem
from app.routes import search_index

client = TestClient(app)

# A realistic-sized catalog — BM25Okapi's idf degenerates on a 2-3 doc corpus.
AGENT_CARD = {
    "name": "security",
    "skills": [
        {"id": "lock", "name": "Lock", "description": "Locks a specific door",
         "tags": ["door"], "examples": ["tranca a porta da frente", "pode trancar a porta", "fecha tudo a chave"]},
        {"id": "unlock", "name": "Unlock", "description": "Unlocks a specific door",
         "tags": ["door"], "examples": ["destranca a porta da frente", "abre a porta da frente"]},
        {"id": "arm", "name": "Arm", "description": "Arms the home alarm",
         "tags": ["alarm"], "examples": ["arma o alarme", "ativa a seguranca da casa"]},
        {"id": "disarm", "name": "Disarm", "description": "Disarms the home alarm",
         "tags": ["alarm"], "examples": ["desarma o alarme", "desativa a seguranca"]},
    ],
}
MCP_TOOLS = {
    "tools": [
        {"name": "turn_on", "description": "Turns a device on",
         "annotations": {"tags": ["light", "tv"],
                         "examples": ["acende a luz da sala", "liga a luz da cozinha", "liga a tv"]}},
        {"name": "turn_off", "description": "Turns a device off",
         "annotations": {"tags": ["light", "tv"],
                         "examples": ["apaga a luz da sala", "desliga a luz da cozinha", "escurece o quarto"]}},
        {"name": "set_brightness", "description": "Sets a light's brightness",
         "annotations": {"tags": ["light"], "examples": ["diminui o brilho da luz", "abaixa a luz"]}},
        {"name": "set_temperature", "description": "Sets an AC target temperature",
         "annotations": {"tags": ["ac"], "examples": ["ajusta a temperatura para 22 graus", "esta muito quente"]}},
        {"name": "open", "description": "Opens a curtain or window",
         "annotations": {"tags": ["curtain"], "examples": ["abre a cortina da sala", "levanta a persiana"]}},
        {"name": "close", "description": "Closes a curtain or window",
         "annotations": {"tags": ["curtain"], "examples": ["fecha a cortina da sala", "abaixa a persiana"]}},
    ],
}


def _handle(request: httpx.Request) -> httpx.Response:
    key = (request.url.host, request.url.path)
    table = {
        ("security", "/.well-known/agent-card.json"): AGENT_CARD,
        ("home-mcp", "/tools"): MCP_TOOLS,
    }
    return httpx.Response(200, json=table[key]) if key in table else httpx.Response(404)


def _mock_client():
    return httpx.Client(transport=httpx.MockTransport(_handle))


@pytest.fixture(autouse=True)
def _seed(monkeypatch):
    """The search index is a module-level singleton; rebuild it from a mocked
    set of sources for each test (also used by POST /refresh)."""
    monkeypatch.setenv("CATALOG_SOURCES", "http://security:8200,http://home-mcp:8100")
    monkeypatch.setattr(catalog, "_new_client", _mock_client)
    catalog.build(search_index)
    yield
    search_index.retain(set())


def test_health_and_ready():
    assert client.get("/health").json() == {"status": "healthy"}
    assert client.get("/ready").json() == {"status": "ready"}


def test_resolve_agents_returns_a_logical_service_and_url():
    body = {"query": "pode trancar a porta da frente?", "top_k": 2}
    hits = client.post("/resolve/agents", json=body).json()

    assert hits
    top = hits[0]
    assert top["kind"] == "agent"
    assert top["service"] == "security"
    assert top["url"] == "http://security:8200"
    assert top["id"] == "lock"
    assert 0.0 < top["score"] <= 1.0


def test_resolve_tools_only_returns_tools():
    hits = client.post("/resolve/tools", json={"query": "acende a luz da sala"}).json()
    assert hits and all(h["kind"] == "tool" for h in hits)
    assert hits[0]["id"] == "turn_on"
    assert hits[0]["url"] == "http://home-mcp:8100"


def test_resolve_spans_both_kinds_and_honours_top_k():
    hits = client.post("/resolve", json={"query": "liga a luz da cozinha", "top_k": 1}).json()
    assert len(hits) == 1


def test_resolve_returns_nothing_for_chitchat():
    assert client.post("/resolve", json={"query": "olá tudo bem por aí?"}).json() == []


def test_refresh_rebuilds_and_reports_counts():
    out = client.post("/refresh").json()
    assert out["indexed"] == 10
    assert out["errors"] == []
    assert set(out["sources"]) == {"http://security:8200", "http://home-mcp:8100"}


def test_catalog_lists_what_is_indexed():
    entries = client.get("/catalog").json()
    ids = {(e["service"], e["id"]) for e in entries}
    assert ("security", "lock") in ids
    assert ("home-mcp", "turn_on") in ids


def test_resolve_carries_tags_and_examples_from_the_descriptor():
    hit = client.post("/resolve/agents", json={"query": "arma o alarme"}).json()[0]
    assert hit["id"] == "arm"
    assert "alarm" in hit["tags"]
    assert any("alarme" in ex for ex in hit["examples"])


def test_index_can_be_seeded_directly_without_sources():
    search_index.retain(set())
    search_index.set_source(
        "tool", "home-mcp", "http://home-mcp:8100",
        [
            CatalogItem(id="brew_coffee", name="Brew", description="brews coffee", examples=["faz um cafe", "prepara o cafe"]),
            CatalogItem(id="play_music", name="Play", description="plays music", examples=["toca uma musica"]),
            CatalogItem(id="lock_door", name="Lock", description="locks a door", examples=["tranca a porta"]),
        ],
    )
    top = client.post("/resolve/tools", json={"query": "pode fazer um cafe?"}).json()[0]
    assert top["id"] == "brew_coffee"


def test_lifespan_builds_the_catalog_on_startup(monkeypatch):
    monkeypatch.setenv("CATALOG_SOURCES", "http://security:8200")
    monkeypatch.setattr(catalog, "_new_client", _mock_client)
    search_index.retain(set())

    with TestClient(app):  # entering the context runs the lifespan
        assert search_index.size() == 4  # security's four skills

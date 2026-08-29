import httpx

from app import catalog
from app.search import SearchIndex

AGENT_CARD = {
    "name": "security",
    "skills": [
        {"id": "lock", "name": "Lock", "description": "Locks a door",
         "tags": ["door", "security"], "examples": ["tranca a porta"]},
        {"id": "arm", "name": "Arm", "description": "Arms the alarm",
         "tags": ["alarm"], "examples": ["arma o alarme"]},
    ],
}

MCP_TOOLS = {
    "tools": [
        {"name": "turn_on", "description": "Turns a device on",
         "annotations": {"tags": ["light"], "examples": ["acende a luz"]}},
        {"name": "turn_off", "description": "Turns a device off",
         "annotations": {"tags": ["light"], "examples": ["apaga a luz"]}},
    ],
}


def _handler(routes):
    def handle(request: httpx.Request) -> httpx.Response:
        key = (request.url.host, request.url.path)
        if key in routes:
            return httpx.Response(200, json=routes[key])
        return httpx.Response(404)

    return handle


def _client(routes):
    return httpx.Client(transport=httpx.MockTransport(_handler(routes)))


def test_build_pulls_an_agent_card_and_mcp_tools_into_the_index():
    routes = {
        ("security", "/.well-known/agent-card.json"): AGENT_CARD,
        ("home-mcp", "/tools"): MCP_TOOLS,
    }
    index = SearchIndex()
    result = catalog.build(
        index,
        srcs=["http://security:8200", "http://home-mcp:8100"],
        client=_client(routes),
    )

    assert result["errors"] == []
    assert result["indexed"] == 4
    kinds = {(d.kind, d.service, d.item.id) for d in index.documents()}
    assert ("agent", "security", "lock") in kinds
    assert ("tool", "home-mcp", "turn_on") in kinds

    hit, _ = index.query("arma o alarme", {"agent"}, 0.3)[0]
    assert hit.item.id == "arm"
    assert hit.url == "http://security:8200"


def test_probe_prefers_the_agent_card_then_falls_back_to_tools():
    # home-mcp has no agent card -> /tools is used
    index = SearchIndex()
    catalog.build(index, srcs=["http://home-mcp:8100"], client=_client({("home-mcp", "/tools"): MCP_TOOLS}))
    assert {d.kind for d in index.documents()} == {"tool"}


def test_a_source_with_neither_endpoint_is_an_error_not_a_crash():
    index = SearchIndex()
    result = catalog.build(index, srcs=["http://dead:9999"], client=_client({}))

    assert index.size() == 0
    assert result["errors"] and result["errors"][0]["source"] == "http://dead:9999"


def test_build_prunes_a_source_that_dropped_out():
    routes = {
        ("security", "/.well-known/agent-card.json"): AGENT_CARD,
        ("home-mcp", "/tools"): MCP_TOOLS,
    }
    index = SearchIndex()
    catalog.build(index, srcs=["http://security:8200", "http://home-mcp:8100"], client=_client(routes))
    assert index.size() == 4

    catalog.build(index, srcs=["http://home-mcp:8100"], client=_client(routes))
    assert {d.service for d in index.documents()} == {"home-mcp"}


def test_sources_parses_a_comma_and_newline_list(monkeypatch):
    monkeypatch.setenv("CATALOG_SOURCES", "http://a:1/,\n http://b:2 ,http://c:3/")
    assert catalog.sources() == ["http://a:1", "http://b:2", "http://c:3"]


def test_sources_is_empty_when_unset(monkeypatch):
    monkeypatch.delenv("CATALOG_SOURCES", raising=False)
    assert catalog.sources() == []

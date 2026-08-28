import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes import agent_registry, mcp_registry, search_index

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean_state():
    """The registries and the search index are module-level singletons; reset
    them so each test is independent."""
    for registry in (agent_registry, mcp_registry):
        registry._services.clear()
        registry._round_robin.clear()
    search_index._by_service.clear()
    search_index._rebuild()
    yield


def registration_payload(name="security", capabilities=None, port=9001):
    return {
        "name": name,
        "port": port,
        "capabilities": capabilities or ["lock_door", "arm_alarm"],
        "protocol": "http",
        "version": "0.1.0",
    }


def test_health_and_ready():
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200


def test_register_and_list_agent():
    response = client.post("/agents/register", json=registration_payload())
    assert response.status_code == 200
    assert response.json()["endpoint"] == "http://testclient:9001"

    listing = client.get("/agents")
    names = [item["name"] for item in listing.json()]
    assert "security" in names


def test_register_and_list_mcp():
    payload = registration_payload(name="home-mcp", capabilities=["turn_light_on"], port=9100)
    response = client.post("/mcp/register", json=payload)
    assert response.status_code == 200

    listing = client.get("/mcp")
    names = [item["name"] for item in listing.json()]
    assert "home-mcp" in names


def test_get_unknown_agent_returns_404_with_explicit_error():
    response = client.get("/agents/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert "error" in body


def test_agent_view_lists_every_instance():
    client.post("/agents/register", json=registration_payload(name="energy", port=9002))
    client.post("/agents/register", json=registration_payload(name="energy", port=9003))

    body = client.get("/agents/energy").json()
    endpoints = {i["endpoint"] for i in body["instances"]}
    assert endpoints == {"http://testclient:9002", "http://testclient:9003"}
    assert body["status"] == "healthy"


def test_capability_filter_returns_matching_agent():
    client.post("/agents/register", json=registration_payload(name="security2", capabilities=["disarm_alarm"]))

    response = client.get("/agents", params={"capability": "disarm_alarm"})
    assert response.status_code == 200
    assert any(item["name"] == "security2" for item in response.json())


def test_capability_filter_no_match_returns_503():
    response = client.get("/agents", params={"capability": "capability-that-does-not-exist"})
    assert response.status_code == 503


def test_correlation_id_is_generated_and_echoed():
    response = client.get("/health")
    assert "x-correlation-id" in response.headers

    incoming = "test-correlation-123"
    response = client.get("/health", headers={"X-Correlation-Id": incoming})
    assert response.headers["x-correlation-id"] == incoming


def test_registration_uses_x_forwarded_for_when_present():
    response = client.post(
        "/agents/register",
        json=registration_payload(name="behind-proxy", port=9500),
        headers={"X-Forwarded-For": "10.0.0.5, 172.17.0.1"},
    )

    assert response.json()["endpoint"] == "http://10.0.0.5:9500"


# ---- /resolve ------------------------------------------------------------------

_TOOLS = [
    {"id": "turn_light_on", "name": "Turn light on", "description": "Turns a light on",
     "examples": ["acende a luz da sala", "liga a luz da cozinha"]},
    {"id": "turn_light_off", "name": "Turn light off", "description": "Turns a light off",
     "examples": ["apaga a luz da sala", "desliga a luz da cozinha"]},
    {"id": "set_temperature", "name": "Set temperature", "description": "Sets an air conditioner temperature",
     "examples": ["ajusta a temperatura para 22 graus", "está muito quente no quarto"]},
    {"id": "lock_door", "name": "Lock door", "description": "Locks a specific door",
     "examples": ["tranca a porta da frente", "pode trancar a porta"]},
    {"id": "unlock_door", "name": "Unlock door", "description": "Unlocks a specific door",
     "examples": ["destranca a porta da frente", "abre a porta da frente"]},
    {"id": "arm_alarm", "name": "Arm alarm", "description": "Arms the home alarm",
     "examples": ["arma o alarme", "ativa a seguranca da casa"]},
    {"id": "open_curtain", "name": "Open curtain", "description": "Opens a specific curtain",
     "examples": ["abre a cortina da sala", "levanta a cortina do quarto"]},
]
_ENERGY_SKILLS = [
    {"id": "inspect_consumption", "name": "Inspect consumption",
     "description": "Reports total energy consumption and top consumers",
     "examples": ["quanto estou gastando de energia", "como está o consumo de energia", "energia da casa"]},
]


def _register_catalog():
    client.post(
        "/mcp/register",
        json={"name": "home-mcp", "port": 9600, "capabilities": [t["id"] for t in _TOOLS],
              "protocol": "mcp", "version": "0.1.0", "catalog": _TOOLS},
    )
    client.post(
        "/agents/register",
        json={"name": "energy", "port": 9601, "capabilities": ["inspect_consumption"],
              "protocol": "http", "version": "0.1.0", "catalog": _ENERGY_SKILLS},
    )


def test_resolve_tools_ranks_the_matching_tool_first():
    _register_catalog()
    body = client.post("/resolve/tools", json={"query": "pode trancar a porta da frente?"}).json()
    assert body[0]["type"] == "tool"
    assert body[0]["name"] == "lock_door"
    assert body[0]["rank"] == 1
    assert 0 < body[0]["score"] <= 1.0
    assert body[0]["endpoint"].endswith(":9600")


def test_resolve_agents_only_returns_agents():
    _register_catalog()
    body = client.post("/resolve/agents", json={"query": "quanto estou gastando de energia"}).json()
    assert body
    assert all(r["type"] == "agent" for r in body)
    assert body[0]["service"] == "energy"


def test_resolve_returns_empty_when_nothing_clears_the_threshold():
    _register_catalog()
    body = client.post("/resolve", json={"query": "olá tudo bem por aí", "threshold": 0.3}).json()
    assert body == []


def test_resolve_respects_top_k():
    _register_catalog()
    body = client.post("/resolve/tools", json={"query": "tranca a porta da frente", "top_k": 1}).json()
    assert len(body) == 1
    assert body[0]["name"] == "lock_door"

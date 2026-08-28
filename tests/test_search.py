from app.models import CatalogItem
from app.search import SearchIndex, normalize

# A realistic-sized tool catalog (BM25Okapi's idf degenerates on tiny corpora,
# same as the live BFA which always has ~12 tools + a few agents).
TOOLS = [
    ("turn_light_on", "Turn light on", "Turns a specific light on",
     ["acende a luz da sala", "liga a luz da cozinha", "pode acender a luz do quarto"]),
    ("turn_light_off", "Turn light off", "Turns a specific light off",
     ["apaga a luz da sala", "desliga a luz da cozinha", "escurece o quarto"]),
    ("set_light_brightness", "Set light brightness", "Sets a light's brightness level",
     ["diminui o brilho da luz do quarto", "coloca a luz da sala em 30", "abaixa a luz"]),
    ("set_temperature", "Set temperature", "Sets an air conditioner target temperature",
     ["ajusta a temperatura para 22 graus", "está muito quente no quarto", "abaixa a temperatura do ar"]),
    ("turn_ac_on", "Turn AC on", "Turns an air conditioner on",
     ["liga o ar condicionado do quarto", "pode ligar o ar"]),
    ("turn_ac_off", "Turn AC off", "Turns an air conditioner off",
     ["desliga o ar condicionado do quarto", "pode desligar o ar"]),
    ("lock_door", "Lock door", "Locks a specific door",
     ["tranca a porta da frente", "pode trancar a porta", "fecha tudo a chave"]),
    ("unlock_door", "Unlock door", "Unlocks a specific door",
     ["destranca a porta da frente", "abre a porta da frente"]),
    ("arm_alarm", "Arm alarm", "Arms the home alarm system",
     ["arma o alarme", "ativa a seguranca da casa"]),
    ("open_curtain", "Open curtain", "Opens a specific curtain",
     ["abre a cortina da sala", "levanta a cortina do quarto"]),
]


def _items(rows):
    return [CatalogItem(id=i, name=n, description=d, examples=ex) for i, n, d, ex in rows]


def _index():
    index = SearchIndex()
    index.set_tools("home-mcp", _items(TOOLS))
    return index


def test_normalize_strips_accents_lowercases_and_drops_stopwords():
    assert normalize("Trancá a Porta!") == ["tranca", "porta"]
    assert normalize("Ar-condicionado 22°C") == ["ar", "condicionado", "22", "c"]
    assert normalize("olá, tudo bem?") == []
    assert normalize("") == []


def test_empty_index_returns_nothing():
    assert SearchIndex().query("anything", {"tool"}, 0.0) == []


def test_index_finds_the_right_tool_by_a_paraphrased_query():
    hits = _index().query("pode trancar a porta?", {"tool"}, threshold=0.3)
    assert hits
    assert hits[0][0].name == "lock_door"


def test_a_paraphrased_temperature_query_hits_set_temperature():
    hits = _index().query("está muito quente, abaixa a temperatura", {"tool"}, threshold=0.3)
    assert hits[0][0].name == "set_temperature"


def test_index_kind_filter_separates_agents_and_tools():
    index = _index()
    index.set_agent("security", ["lock_door"], _items([("lock_door", "Lock door", "Locks a door", [])]))

    assert all(d.kind == "agent" for d, _ in index.query("lock door", {"agent"}, 0.0))
    assert all(d.kind == "tool" for d, _ in index.query("lock door", {"tool"}, 0.0))


def test_removing_a_service_drops_its_documents():
    index = _index()
    assert index.query("trancar a porta", {"tool"}, 0.3)

    index.remove_service("tool", "home-mcp")
    assert index.query("trancar a porta", {"tool"}, 0.3) == []


def test_chitchat_query_clears_no_document():
    assert _index().query("olá tudo bem por aí?", {"tool"}, 0.3) == []


def test_top_score_is_normalized_coverage_between_0_and_1():
    hits = _index().query("apaga a luz da cozinha", {"tool"}, 0.3)
    assert hits
    assert hits[0][0].name == "turn_light_off"
    assert 0.0 < hits[0][1] <= 1.0

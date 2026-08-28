from app.models import ServiceRegistration
from app.registry import ServiceRegistry


def make_registration(name="orchestrator", capabilities=None, port=9000):
    return ServiceRegistration(
        name=name,
        port=port,
        capabilities=capabilities or ["orchestrate"],
        protocol="http",
        version="0.1.0",
    )


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def test_register_new_service():
    registry = ServiceRegistry()
    record = registry.register(make_registration(), host="orchestrator")

    assert record.name == "orchestrator"
    assert record.status == "healthy"
    assert record.endpoint == "http://orchestrator:9000"
    assert registry.get("orchestrator") is not None


def test_register_builds_endpoint_from_path_and_ssl():
    registry = ServiceRegistry()
    registration = ServiceRegistration(
        name="home-mcp",
        port=8100,
        path="/mcp",
        use_ssl=True,
        capabilities=["turn_light_on"],
        protocol="mcp",
        version="0.1.0",
    )

    record = registry.register(registration, host="172.19.0.3")

    assert record.endpoint == "https://172.19.0.3:8100/mcp"


def test_same_endpoint_registered_twice_is_one_instance():
    registry = ServiceRegistry()
    registry.register(make_registration(port=9000), host="orchestrator")
    registry.register(make_registration(port=9000), host="orchestrator")

    view = registry.get_view("orchestrator")
    assert len(view.instances) == 1
    assert len(registry.list()) == 1


def test_different_endpoints_same_name_are_separate_instances():
    registry = ServiceRegistry()
    registry.register(make_registration(port=9000), host="orchestrator")
    registry.register(make_registration(port=9001), host="orchestrator")

    view = registry.get_view("orchestrator")
    endpoints = {i.endpoint for i in view.instances}
    assert endpoints == {"http://orchestrator:9000", "http://orchestrator:9001"}
    # list() still collapses to one record per logical service
    assert len(registry.list()) == 1


def test_round_robin_across_healthy_instances():
    registry = ServiceRegistry()
    registry.register(make_registration(name="security", capabilities=["lock_door"], port=9000), host="a")
    registry.register(make_registration(name="security", capabilities=["lock_door"], port=9000), host="b")

    picks = {registry.find_by_capability("lock_door").endpoint for _ in range(6)}
    assert picks == {"http://a:9000", "http://b:9000"}


def test_find_by_capability_exact_match():
    registry = ServiceRegistry()
    registry.register(make_registration(name="security", capabilities=["lock_door", "arm_alarm"]), host="security")
    registry.register(make_registration(name="environment", capabilities=["turn_light_on"]), host="environment")

    match = registry.find_by_capability("lock_door")

    assert match is not None
    assert match.name == "security"


def test_find_by_capability_no_match_returns_none():
    registry = ServiceRegistry()
    registry.register(make_registration(name="security", capabilities=["lock_door"]), host="security")

    assert registry.find_by_capability("set_temperature") is None


def test_instance_goes_unhealthy_after_ttl_then_is_evicted_after_grace():
    clock = FakeClock()
    registry = ServiceRegistry(clock=clock, ttl_seconds=45, grace_seconds=300)
    registry.register(make_registration(name="security", capabilities=["lock_door"]), host="security")

    assert registry.find_by_capability("lock_door") is not None

    clock.advance(60)  # past TTL, within grace
    assert registry.find_by_capability("lock_door") is None
    assert registry.get_view("security").status == "unhealthy"

    clock.advance(300)  # past grace
    assert registry.get_view("security") is None


def test_heartbeat_keeps_an_instance_healthy():
    clock = FakeClock()
    registry = ServiceRegistry(clock=clock, ttl_seconds=45)
    reg = make_registration(name="security", capabilities=["lock_door"])
    registry.register(reg, host="security")

    clock.advance(30)
    registry.register(reg, host="security")  # heartbeat
    clock.advance(30)  # 30s since the heartbeat, still within TTL

    assert registry.find_by_capability("lock_door") is not None

from starlette.requests import Request

from app.client_host import resolve_client_host


def make_request(headers: dict[str, str], client_host: str = "1.2.3.4") -> Request:
    scope = {
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": (client_host, 12345),
    }
    return Request(scope)


def test_resolve_client_host_uses_direct_connection_by_default():
    request = make_request(headers={}, client_host="172.19.0.3")

    assert resolve_client_host(request) == "172.19.0.3"


def test_resolve_client_host_prefers_x_forwarded_for_first_hop():
    request = make_request(headers={"X-Forwarded-For": "10.0.0.5, 172.17.0.1"})

    assert resolve_client_host(request) == "10.0.0.5"

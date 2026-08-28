from starlette.requests import Request

FORWARDED_FOR_HEADER = "X-Forwarded-For"


def resolve_client_host(request: Request) -> str:
    """Resolves the network host of the caller for self-registration purposes.

    Prefers X-Forwarded-For (first hop = original client) when present, to
    support a future reverse proxy in front of the BFA. Falls back to the
    direct TCP connection's source address, which is what today's Docker
    Compose topology (no proxy between services) actually uses.

    X-Forwarded-For is caller-supplied and spoofable; treated here as a
    convenience for internal registration traffic, not as a trust boundary.
    """
    forwarded_for = request.headers.get(FORWARDED_FOR_HEADER)
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    return request.client.host

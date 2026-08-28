from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.client_host import resolve_client_host
from app.models import ErrorResponse, ResolveRequest, ResolveResult, ServiceRegistration
from app.registry import ServiceRegistry
from app.search import SearchIndex

agent_registry = ServiceRegistry()
mcp_registry = ServiceRegistry()
search_index = SearchIndex()

router = APIRouter()


def _not_found(request: Request, name: str) -> JSONResponse:
    correlation_id = getattr(request.state, "correlation_id", None)
    return JSONResponse(
        status_code=404,
        content=ErrorResponse(error=f"service '{name}' is not registered", correlation_id=correlation_id).model_dump(),
    )


def _no_match(request: Request, capability: str) -> JSONResponse:
    correlation_id = getattr(request.state, "correlation_id", None)
    return JSONResponse(
        status_code=503,
        content=ErrorResponse(
            error=f"no healthy agent available for capability '{capability}'", correlation_id=correlation_id
        ).model_dump(),
    )


# ---- registration ------------------------------------------------------------


@router.post("/agents/register")
def register_agent(registration: ServiceRegistration, request: Request):
    record = agent_registry.register(registration, resolve_client_host(request))
    search_index.set_agent(registration.name, registration.capabilities, registration.catalog)
    return record


@router.post("/mcp/register")
def register_mcp(registration: ServiceRegistration, request: Request):
    record = mcp_registry.register(registration, resolve_client_host(request))
    search_index.set_tools(registration.name, registration.catalog)
    return record


# ---- discovery -------------------------------------------------------------


@router.get("/agents")
def list_agents(request: Request, capability: str | None = None):
    if capability is None:
        return agent_registry.list()

    match = agent_registry.find_by_capability(capability)
    if match is None:
        return _no_match(request, capability)
    return [match]


@router.get("/agents/{name}")
def get_agent(name: str, request: Request):
    view = agent_registry.get_view(name)
    if view is None:
        return _not_found(request, name)
    return view


@router.get("/mcp")
def list_mcp():
    return mcp_registry.list()


@router.get("/mcp/{name}")
def get_mcp(name: str, request: Request):
    view = mcp_registry.get_view(name)
    if view is None:
        return _not_found(request, name)
    return view


# ---- resolve (BM25 ranking; the BFA ranks, the caller decides) ------------


def _resolve(body: ResolveRequest, kinds: set[str]) -> list[ResolveResult]:
    hits = search_index.query(body.query, kinds, body.threshold)

    results: list[ResolveResult] = []
    for doc, coverage in hits:
        registry = agent_registry if doc.kind == "agent" else mcp_registry
        record = registry.resolve(doc.service)
        if record is None:  # no healthy instance right now
            continue
        results.append(
            ResolveResult(
                type=doc.kind,
                service=doc.service,
                name=doc.name,
                endpoint=record.endpoint,
                protocol=record.protocol,
                score=round(coverage, 3),
                rank=len(results) + 1,
            )
        )
        if len(results) >= max(0, body.top_k):
            break
    return results


@router.post("/resolve")
def resolve(body: ResolveRequest):
    return _resolve(body, {"agent", "tool"})


@router.post("/resolve/agents")
def resolve_agents(body: ResolveRequest):
    return _resolve(body, {"agent"})


@router.post("/resolve/tools")
def resolve_tools(body: ResolveRequest):
    return _resolve(body, {"tool"})


# ---- health --------------------------------------------------------------------


@router.get("/health")
def health():
    return {"status": "healthy"}


@router.get("/ready")
def ready():
    return {"status": "ready"}

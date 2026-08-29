from fastapi import APIRouter

from app import catalog
from app.models import ResolveRequest, ResolveResult
from app.search import SearchIndex

# The catalog is derived state: pulled from CATALOG_SOURCES on startup and on
# POST /refresh. No registration, no per-instance registry.
search_index = SearchIndex()

router = APIRouter()


def _resolve(body: ResolveRequest, kinds: set[str]) -> list[ResolveResult]:
    hits = search_index.query(body.query, kinds, body.threshold)
    results: list[ResolveResult] = []
    for doc, coverage in hits:
        results.append(
            ResolveResult(
                kind=doc.kind,
                service=doc.service,
                url=doc.url,
                id=doc.item.id or doc.service,
                name=doc.item.name,
                description=doc.item.description,
                tags=list(doc.item.tags),
                examples=list(doc.item.examples),
                score=round(coverage, 3),
            )
        )
        if len(results) >= max(0, body.top_k):
            break
    return results


@router.post("/resolve", response_model=list[ResolveResult])
def resolve(body: ResolveRequest):
    return _resolve(body, {"agent", "tool"})


@router.post("/resolve/agents", response_model=list[ResolveResult])
def resolve_agents(body: ResolveRequest):
    return _resolve(body, {"agent"})


@router.post("/resolve/tools", response_model=list[ResolveResult])
def resolve_tools(body: ResolveRequest):
    return _resolve(body, {"tool"})


@router.post("/refresh")
def refresh():
    """Re-pull every source and rebuild the catalog. Call on a deploy that
    changed a service's capabilities."""
    return catalog.build(search_index)


@router.get("/catalog")
def list_catalog():
    """What is currently indexed — for debugging."""
    return [
        {"kind": d.kind, "service": d.service, "url": d.url, "id": d.item.id, "tags": list(d.item.tags)}
        for d in search_index.documents()
    ]


@router.get("/health")
def health():
    return {"status": "healthy"}


@router.get("/ready")
def ready():
    return {"status": "ready"}

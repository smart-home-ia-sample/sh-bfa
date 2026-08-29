from pydantic import BaseModel


class CatalogItem(BaseModel):
    """A skill (agent) or a tool (MCP) as it should be found by `/resolve`."""

    id: str = ""
    name: str = ""
    description: str = ""
    tags: list[str] = []
    examples: list[str] = []


class ResolveRequest(BaseModel):
    query: str
    top_k: int = 3
    threshold: float = 0.3


class ResolveResult(BaseModel):
    kind: str  # "agent" | "tool"
    service: str  # logical service name (DNS), e.g. "security"
    url: str  # base URL to call — the platform load-balances behind it
    id: str  # skill id / verb / tool name
    name: str = ""
    description: str = ""
    tags: list[str] = []
    examples: list[str] = []
    score: float  # query coverage, 0..1


class ErrorResponse(BaseModel):
    error: str
    correlation_id: str | None = None

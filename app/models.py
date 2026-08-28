import time

from pydantic import BaseModel, Field


class CatalogItem(BaseModel):
    """A skill (agent) or a tool (MCP) as it should be found by `/resolve`."""

    id: str = ""
    name: str = ""
    description: str = ""
    tags: list[str] = []
    examples: list[str] = []


class ServiceRegistration(BaseModel):
    name: str
    port: int
    capabilities: list[str]
    protocol: str
    version: str
    path: str = ""
    use_ssl: bool = False
    catalog: list[CatalogItem] = []


class ResolveRequest(BaseModel):
    query: str
    top_k: int = 3
    threshold: float = 0.3


class ResolveResult(BaseModel):
    type: str  # "agent" | "tool"
    service: str
    name: str  # tool name, skill id, or service name for a bare agent
    endpoint: str
    protocol: str
    score: float  # normalized to the top hit of this result set
    rank: int


class ServiceRecord(BaseModel):
    """Flat view of one instance of a logical service — the shape every
    existing consumer (`GET /agents`, `GET /mcp`, capability lookup) expects."""

    name: str
    endpoint: str
    capabilities: list[str]
    protocol: str
    version: str
    status: str = "healthy"
    last_registered_at: float = Field(default_factory=time.time)


class InstanceView(BaseModel):
    endpoint: str
    status: str
    last_registered_at: float


class ServiceView(BaseModel):
    """Richer view for `GET /agents/{name}` — the logical service and every
    instance the BFA currently knows about."""

    name: str
    capabilities: list[str]
    protocol: str
    version: str
    status: str  # healthy if any instance is healthy
    instances: list[InstanceView]


class ErrorResponse(BaseModel):
    error: str
    correlation_id: str | None = None

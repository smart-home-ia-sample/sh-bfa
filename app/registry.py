from __future__ import annotations

import itertools
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from app.models import InstanceView, ServiceRecord, ServiceRegistration, ServiceView

# Liveness comes from the re-registration heartbeat (default every 15s). An
# instance is healthy while it was seen within the TTL; past the grace window it
# is dropped entirely. No active probing, no circuit breaker.
DEFAULT_TTL_SECONDS = float(os.environ.get("REGISTRATION_TTL_SECONDS", "45"))
DEFAULT_GRACE_SECONDS = float(os.environ.get("REGISTRATION_GRACE_SECONDS", "300"))


@dataclass
class _Instance:
    endpoint: str
    last_seen: float


@dataclass
class _Service:
    name: str
    capabilities: list[str]
    protocol: str
    version: str
    instances: dict[str, _Instance] = field(default_factory=dict)  # keyed by endpoint


class ServiceRegistry:
    """In-memory registry for either agents or MCP servers.

    A logical service (by name) can have several instances; an instance is
    identified by its resolved endpoint. Re-registering the same endpoint just
    refreshes its `last_seen`; a new endpoint for a known name adds an instance.
    """

    def __init__(
        self,
        clock: Callable[[], float] = time.time,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        grace_seconds: float = DEFAULT_GRACE_SECONDS,
    ) -> None:
        self._services: dict[str, _Service] = {}
        self._lock = threading.Lock()
        self._clock = clock
        self._ttl = ttl_seconds
        self._grace = grace_seconds
        self._round_robin: dict[str, itertools.count] = {}

    # ---- registration ----------------------------------------------------

    def register(self, registration: ServiceRegistration, host: str) -> ServiceRecord:
        scheme = "https" if registration.use_ssl else "http"
        endpoint = f"{scheme}://{host}:{registration.port}{registration.path}"
        now = self._clock()

        with self._lock:
            service = self._services.get(registration.name)
            if service is None:
                service = _Service(
                    name=registration.name,
                    capabilities=list(registration.capabilities),
                    protocol=registration.protocol,
                    version=registration.version,
                )
                self._services[registration.name] = service
            else:
                service.capabilities = list(registration.capabilities)
                service.protocol = registration.protocol
                service.version = registration.version

            instance = service.instances.get(endpoint)
            if instance is None:
                service.instances[endpoint] = _Instance(endpoint=endpoint, last_seen=now)
            else:
                instance.last_seen = now

        return ServiceRecord(
            name=registration.name,
            endpoint=endpoint,
            capabilities=list(registration.capabilities),
            protocol=registration.protocol,
            version=registration.version,
            status="healthy",
            last_registered_at=now,
        )

    # ---- liveness ------------------------------------------------------------

    def _status(self, instance: _Instance, now: float) -> str:
        return "healthy" if (now - instance.last_seen) <= self._ttl else "unhealthy"

    def _prune(self, now: float) -> None:
        for service in list(self._services.values()):
            for endpoint, instance in list(service.instances.items()):
                if (now - instance.last_seen) > self._grace:
                    del service.instances[endpoint]
            if not service.instances:
                del self._services[service.name]

    def _healthy_instances(self, service: _Service, now: float) -> list[_Instance]:
        return [i for i in service.instances.values() if self._status(i, now) == "healthy"]

    def _pick_instance(self, service: _Service, now: float) -> _Instance | None:
        healthy = self._healthy_instances(service, now)
        if not healthy:
            return None
        counter = self._round_robin.setdefault(service.name, itertools.count())
        return healthy[next(counter) % len(healthy)]

    def _flat_record(self, service: _Service, instance: _Instance, now: float) -> ServiceRecord:
        return ServiceRecord(
            name=service.name,
            endpoint=instance.endpoint,
            capabilities=list(service.capabilities),
            protocol=service.protocol,
            version=service.version,
            status=self._status(instance, now),
            last_registered_at=instance.last_seen,
        )

    # ---- lookups ----------------------------------------------------------

    def get(self, name: str) -> ServiceRecord | None:
        """One flat record for the named service — a healthy instance if there
        is one, otherwise a representative (with status unhealthy)."""
        now = self._clock()
        with self._lock:
            self._prune(now)
            service = self._services.get(name)
            if service is None:
                return None
            instance = self._pick_instance(service, now) or next(iter(service.instances.values()), None)
            if instance is None:
                return None
            return self._flat_record(service, instance, now)

    def resolve(self, name: str) -> ServiceRecord | None:
        """A flat record for a **healthy** instance of the named service, or
        None if the service has no healthy instance right now."""
        now = self._clock()
        with self._lock:
            self._prune(now)
            service = self._services.get(name)
            if service is None:
                return None
            instance = self._pick_instance(service, now)
            return self._flat_record(service, instance, now) if instance else None

    def get_view(self, name: str) -> ServiceView | None:
        now = self._clock()
        with self._lock:
            self._prune(now)
            service = self._services.get(name)
            if service is None:
                return None
            return self._service_view(service, now)

    def list(self) -> list[ServiceRecord]:
        """One flat record per logical service (healthy instance preferred)."""
        now = self._clock()
        with self._lock:
            self._prune(now)
            records = []
            for service in self._services.values():
                instance = self._pick_instance(service, now) or next(iter(service.instances.values()), None)
                if instance is not None:
                    records.append(self._flat_record(service, instance, now))
            return records

    def list_views(self) -> list[ServiceView]:
        now = self._clock()
        with self._lock:
            self._prune(now)
            return [self._service_view(s, now) for s in self._services.values()]

    def find_by_capability(self, capability: str) -> ServiceRecord | None:
        now = self._clock()
        with self._lock:
            self._prune(now)
            candidates = self._match_capability(capability)
            for service in candidates:
                instance = self._pick_instance(service, now)
                if instance is not None:
                    return self._flat_record(service, instance, now)
            return None

    # ---- internals ------------------------------------------------------------

    def _match_capability(self, capability: str) -> list[_Service]:
        exact = [s for s in self._services.values() if capability in s.capabilities]
        if exact:
            return exact
        return [
            s
            for s in self._services.values()
            if any(capability in cap or cap in capability for cap in s.capabilities)
        ]

    def _service_view(self, service: _Service, now: float) -> ServiceView:
        instances = [
            InstanceView(endpoint=i.endpoint, status=self._status(i, now), last_registered_at=i.last_seen)
            for i in service.instances.values()
        ]
        overall = "healthy" if any(v.status == "healthy" for v in instances) else "unhealthy"
        return ServiceView(
            name=service.name,
            capabilities=list(service.capabilities),
            protocol=service.protocol,
            version=service.version,
            status=overall,
            instances=instances,
        )

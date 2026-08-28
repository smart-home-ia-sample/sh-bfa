# sh-bfa

Backend-for-Agents: service registry (heartbeat TTL, round-robin over instances) + BM25 `/resolve` over the agent/tool catalog.

Part of the **Smart Home AI** system — architecture, the full `docker compose`
stack and the end-to-end tests live in `sh-infra`.

## Run the tests
```
pip install -r requirements-dev.txt   # needs sh-common from the registry
pytest
```

## Build the image
```
docker build -t sh-bfa .
```

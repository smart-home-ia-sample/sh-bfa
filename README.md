# sh-bfa

Backend-for-Agents: service registry (heartbeat TTL, round-robin over instances) + BM25 `/resolve` over the agent/tool catalog.

Part of the **Smart Home AI** system — architecture, the full `docker compose`
stack and the end-to-end tests live in `sh-infra`.

## Run the tests
```
pip install -r requirements-dev.txt   # pulls sh-common from its public GitHub tag
pytest
```

## Build the image
```
docker build -t sh-bfa .              # sh-common resolved from GitHub (public)
```

`--build-arg SH_COMMON_SOURCE=local --build-context sh_common=../sh-common`
builds against a sibling checkout instead (offline / coordinated changes).

## CI

| Workflow | Runs |
| --- | --- |
| `test` | `pytest` with coverage on every PR / `main` push; fails below the `fail_under` in `pyproject.toml`, posts a coverage summary on the PR (check `test / coverage`) |
| `codeql` | CodeQL analysis (Python) on PRs, `main`, and weekly |
| `ci` | builds the Docker image on every PR; on `main` also pushes `ghcr.io/<owner>/sh-bfa:latest` + `:<sha>` |

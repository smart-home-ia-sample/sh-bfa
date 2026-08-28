# sh-bfa

Backend-for-Agents: a **stateless capability catalog + semantic resolver**. On
startup (and on `POST /refresh`) it *pulls* each service's descriptor listed in
`CATALOG_SOURCES` — an A2A agent card (`/.well-known/agent-card.json`) or the MCP
`/tools` map — and indexes the skills/tools with BM25 (PT stemming + synonyms).
`POST /resolve[/agents|/tools]` ranks them for a query and returns **logical
service names + URLs**; the platform (k8s / compose) load-balances behind those.
No self-registration, no per-instance registry — see `sh-infra/spec/13`.

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

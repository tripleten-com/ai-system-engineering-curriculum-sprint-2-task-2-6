# Coldline Task 2.6 — Schema migration path

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/tripleten-com/ai-system-engineering-curriculum-sprint-2-task-2-6/tree/main)

## Start the system

Prerequisites are Python 3.12 and Docker with Compose v2. The supplied bootstrap supports macOS
arm64/x86-64, Windows x86-64, and Linux x86-64/aarch64, and installs pinned uv 0.11.8 under
`.tools/bin`. If your computer cannot run the stack locally, use the Codespaces button above.

On macOS and most Linux distributions the interpreter is `python3`; substitute it wherever these
commands say `python`.

```shell
python infra/scripts/bootstrap.py
./.tools/bin/uv sync --frozen
./.tools/bin/uv run --frozen poe preflight
./.tools/bin/uv run --frozen poe start
./.tools/bin/uv run --frozen poe ready
./.tools/bin/uv run --frozen poe ingest
./.tools/bin/uv run --frozen poe baseline
```

PowerShell and POSIX wrappers are available under `infra/scripts/`. After uv is on `PATH`, the
shorter `uv run --frozen poe <task>` form works.

| Service | Local URL | Purpose |
|---|---|---|
| API | `http://localhost:8000` | Submit exception workflows and retrieval queries |
| Grafana | `http://localhost:3000` | Use the focused diagnostics dashboard |
| Prometheus | `http://localhost:9090` | Query bounded metrics |
| Jaeger | `http://localhost:16686` | Inspect local traces |
| LocalStack S3 | `http://localhost:4566` | Inspect the emulated object-storage endpoint |

Each of these ports can be overridden by setting the matching `COLDLINE_API_HOST_PORT`,
`COLDLINE_GRAFANA_HOST_PORT`, `COLDLINE_PROMETHEUS_HOST_PORT`, `COLDLINE_JAEGER_HOST_PORT`, or
`COLDLINE_LOCALSTACK_HOST_PORT` environment variable in your shell environment or a local `.env`
file (copy `.env.example`) if a default collides with something already running on your machine.
Keep the override in place for every `poe` command.

If you change the API port, also set `COLDLINE_API_HOST_PORT` in the shell that runs
`poe load-test`: this command does not read `.env`. Use the same port for startup and load testing.
For example, to use port 8001, run the command for your shell before starting the system:

| Shell | Set the API host port |
|---|---|
| PowerShell | `$env:COLDLINE_API_HOST_PORT = "8001"` |
| macOS/Linux (POSIX) | `export COLDLINE_API_HOST_PORT=8001` |

PostgreSQL, Redis, worker metrics, and OTLP remain inside the Compose network. Codespaces uses the
same `compose.yaml` and keeps every forwarded port private.

## Command path

For a fresh investigation, run the supplied commands in this order:

```text
poe start
poe ready
poe ingest
poe baseline
poe verify
```

| Command | Use |
|---|---|
| `poe ingest` | Run the supplied baseline corpus ingestion inside the API container |
| `poe baseline` | Run every published query and print the baseline evaluation report |
| `poe migrate-new` | Generate an empty migration revision, on the host, with no database |
| `poe migrate` | Apply every migration inside the API container |
| `poe migrate-current` | Print the revision the database is stamped at |
| `poe migrate-down` | Roll back the most recent migration |
| `poe migration` | Rebuild, ingest, then run this Task's schema-migration checks |
| `poe student-tests` | Run your own tests under `tests/student/` |
| `poe unit` | Run fast isolated behavior tests |
| `poe contract` | Check interfaces, boundaries, submissions, and repository structure |
| `poe smoke` | Check the initialized running platform |
| `poe e2e` | Run the external API-to-worker workflow |
| `poe verify` | Run the public student verification path |
| `poe scenario` | Run the supplied exception-workflow walkthrough |
| `poe load-test` | Run this repository's supplied traffic profile |
| `poe reset-baseline` | Clear exception and Redis data, then restart the worker between load runs |
| `poe restart` | Restart the existing API and worker containers **without rebuilding**; run `poe start` instead after editing source |
| `poe stop` | Remove containers and the network, keeping named volumes |
| `poe reset` | Remove containers, the network, and local named volumes |

`poe ingest` is idempotent: running it twice produces the same rows, the same counts, and the same
corpus digest. `poe reset` removes the database volume, so run `poe ingest` again after a reset.

For Task 2.6, `poe verify` rebuilds and starts the stack, ingests the supplied corpus, then runs
readiness, smoke tests, the end-to-end exception workflow, the answer-sheet checks, the schema
migration checks, and your own tests under `tests/student/`.

`poe verify` begins with `poe start`, which is `up --build --wait`. Your migration runs inside the
API container, so the container the checks talk to has to be built from your checkout rather than
from a previous one.

Pass the revision message straight through:

```shell
poe migrate-new -m "add retention class"
```

## Folder map

```text
repository root/
├── docs/                Student guidance, public contracts, and fidelity notes
│   ├── contracts/       Machine-readable public contracts
│   ├── fidelity/        Local-runtime boundary notes
│   ├── retrieval/       Supplied retrieval pipeline reference
│   └── student/         This Task's student contract
├── infra/               Local setup and runtime configuration
│   ├── corpus/          Supplied synthetic corpus, custody record, and query set
│   └── postgres/        Database initialization and the migration baseline stamp
├── loadtest/            Supplied traffic profile and provider-latency harness
├── migrations/          Alembic environment, revision template, and revisions
│   └── versions/        The supplied baseline revision, and the one you write
├── src/
│   ├── api/             HTTP application code, the retrieval and document paths, composition
│   ├── worker/          Background application code
│   ├── domain/          Shared domain code, contracts, service and repository contracts
│   ├── ports/           Application interfaces
│   └── adapters/        Technology-specific implementations
└── tests/
    ├── unit/            Isolated behavior checks
    ├── contract/        Interface, retrieval, migration, and repository checks
    ├── doubles/         Supplied deterministic test doubles
    ├── student/         Your own tests
    ├── smoke/           Running-platform checks
    └── e2e/             Supplied workflow tools and checks
```

## Overview

Use the Task 2.6 lesson to decide what to do. This README covers local setup and repository
orientation.

1. `README.md` — local setup, commands, and permitted changes.
2. [`docs/student/task-2-6-contract.md`](docs/student/task-2-6-contract.md) — the required schema
   change, the supplied environment, and where each check looks.
3. `migrations/versions/0001baseline_coldline_initialized_schema.py` — the baseline your revision
   chains from, and why it is empty.
4. `migrations/env.py` — how a migration reaches the database, and why autogeneration is off.
5. `infra/postgres/` — the explicit SQL the initializer applies before any migration runs.
6. `migrations/versions/` — where your generated revision lands.

The application source lives in five flat packages:

| Package | Responsibility |
|---|---|
| `api` | HTTP delivery, API use cases, the retrieval workflow, versioned routes, configuration, and composition |
| `worker` | Background processing, retries, configuration, and composition |
| `domain` | Provider-neutral contracts, state rules, identity, redaction, embedding, chunking, fusion, access constraints, service and repository contracts |
| `ports` | Exactly five visible application interfaces |
| `adapters` | PostgreSQL, pgvector retrieval, Redis Streams, S3-compatible object storage, deterministic model, logs, traces |

`src/api/bootstrap.py` and `src/worker/bootstrap.py` compose each process from its settings and
adapters. Process settings live in `src/api/config.py` and `src/worker/config.py`; other modules
receive settings or collaborators through function and constructor arguments.

## The five ports

Find the available interfaces in `src/ports/`. A port describes an application capability; an
adapter provides it using a concrete technology. Determine which ports are active from your own
runtime evidence rather than from this guide.

| Port | General responsibility |
|---|---|
| `ModelProvider` | Call an AI model service |
| `Retriever` | Look up relevant context or documents |
| `ObjectStore` | Store large binary objects or files |
| `JobQueue` | Publish and consume background work |
| `SecretProvider` | Read API keys and credentials |

## Schema ownership

Two mechanisms create schema in this repository, and they do not overlap.

| Mechanism | What it owns | When it runs |
|---|---|---|
| `infra/postgres/0*.sql` | The initialized schema: `exceptions`, `documents`, `chunks`, `idempotency_claims`, and the `alembic_version` stamp | The initializer, on every start, idempotently |
| `migrations/versions/` | Every change made *after* that point | `poe migrate`, on request |

The baseline revision is empty on purpose. It names the schema as initialized, and it is where a
rollback stops. `infra/postgres/` is protected: this Task asks for a migration, not an edit to the
initialization SQL.

## Document API

The document surface and the repository behind it are supplied.

```text
POST /api/v1/documents                        -> persist one document and its chunks atomically
GET  /api/v1/documents?tenant_id=&clearance=  -> list the documents one scope may read
GET  /api/v1/documents/{id}?tenant_id=&clearance=         -> one document, or 404 when out of scope
GET  /api/v1/documents/{id}/chunks?tenant_id=&clearance=  -> that document's readable chunks
```

## Versioned API

Version 1 and the version 2 document endpoint are both supplied from this Task onward.

```text
POST /api/v2/documents   DocumentV2Request  -> DocumentV2Response
```

The reference version 2 endpoint from Task 2.5 is composed for you here. Your own Task 2.5
implementation — of either supported operation — stays in that Task's pull request.

## Retrieval API

Both endpoints are supplied and are not student work.

```text
POST /api/v1/retrieval/search
  {"query_id": "...", "text": "...",
   "authorization": {"tenant_id": "...", "clearance": "standard"},
   "explain": false}
  -> ranked results, per-stage evidence, prompt context, citations

GET  /api/v1/corpus/objects?prefix=corpus/
  -> the object keys visible through the published ObjectStore port
```

Set `"explain": true` to add the authorization stage's readable pool to the evidence. That costs
one extra query, so ordinary requests leave it off.

## Test levels

| Level | Requires Compose | Main question |
|---|---:|---|
| Unit | No | Does one responsibility behave correctly, including failures? |
| Contract | Some | Do interfaces, schemas, paths, and dependency rules stay compatible? |
| Smoke | Yes | Did the complete local platform initialize and become observable? |
| E2E | Yes | Can an external client complete the supplied workflow? |

Contract checks marked `runtime` need the running stack. `poe contract` skips them; `poe verify`
and `poe runtime-contract` run them.

## Submission checks

Run `poe verify` locally before opening your student pull request. Public GitHub CI repeats
the student checks. The course platform (CMS) runs the required protected grading separately
and associates its results with your submission commit. A green template-export check, or a
skipped student check on an `export/` branch, is not a passing grade. You do not configure
GitHub grading secrets. Follow the Task lesson's instructor-review and progression policy.

## Task boundary

Task 2.6 asks you to write **one reversible migration** that adds a `retention_class` column to the
`documents` table, apply it, verify the resulting database state, roll it back, and record the
revision identifier Alembic generated for it.

The Alembic environment, the revision template, and the baseline revision are supplied. You
generate a revision and write both `upgrade()` and `downgrade()` yourself. Autogeneration is
deliberately unavailable: this schema is owned by explicit SQL rather than by an ORM, so there is
no model metadata to diff, and the rollback has to be written rather than inferred.

These paths are student-editable:

- anything you add under `migrations/versions/`
- anything you add under `tests/student/`
- `submission.yaml`

`alembic.ini`, `migrations/env.py`, `migrations/script.py.mako`, the supplied baseline revision,
`infra/postgres/`, and the whole of `src/` are protected. Read
[`docs/student/task-2-6-contract.md`](docs/student/task-2-6-contract.md) for the required change
and where each check looks.

The supplied defaults are `top_k = 3` and `dense_weight = 0.5`. Each arm returns a fixed
candidate pool of 12 rows before fusion, so the two parameters change what fusion selects without
changing what the arms see.

### Student walkthrough

See **Task 2.6: Schema migration path** in your course platform for the full walkthrough. In
outline: start the stack and ingest the corpus so the table holds rows, read the supplied baseline
revision and `migrations/env.py`, generate a revision with `poe migrate-new`, write `upgrade()`
and `downgrade()`, rebuild with `poe start`, apply it with `poe migrate`, check the state with
`poe migrate-current` and psql, roll it back with `poe migrate-down` and confirm nothing was lost,
record the revision identifier, run `poe migration` and then `poe verify`, and open your pull
request.

## Operational limits

This local system does not authenticate users, terminate TLS, or manage production secrets.
A retrieval request states its own tenancy and clearance, so that context is an asserted
identity rather than a verified one. The Compose PostgreSQL password and the LocalStack access keys
are local-only non-secret credentials. Never place real credentials, personal data, or production
records in this repository, including in `infra/corpus/`.

This local migration path also makes no production claim. It runs against one database with no
concurrent traffic, no replica, and no backup, so it demonstrates reversibility rather than a safe
production rollout procedure.

Named volumes preserve local PostgreSQL, Redis, Prometheus, Grafana, and Jaeger state across
`poe stop`. LocalStack object contents are deliberately not persisted; the initializer re-uploads
the supplied corpus artifacts on every start. The `poe reset` command deletes the named volumes.
This topology makes no backup, replication, high-availability, disaster-recovery, capacity,
latency-SLO, or availability claim.

See [JobQueue fidelity](docs/fidelity/JobQueue.md),
[ModelProvider fidelity](docs/fidelity/ModelProvider.md),
[ObjectStore fidelity](docs/fidelity/ObjectStore.md), and
[Retriever fidelity](docs/fidelity/Retriever.md) for the active adapter boundaries. The
[local runtime evidence](docs/fidelity/local-runtime.md) records the current measurement and its
qualification limits.

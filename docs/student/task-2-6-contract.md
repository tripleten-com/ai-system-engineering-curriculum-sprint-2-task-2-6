# Task 2.6 — Schema migration contract

Write one reversible migration, apply it, verify the database state, roll it back, and record the
revision identifier Alembic generated for it in `submission.yaml`.

## The required change

Add one column to the `documents` table.

| Property | Required value |
|---|---|
| Table | `documents` |
| Column | `retention_class` |
| Type | text |
| Nullable | no |
| Default | `'standard'` |
| Permitted values | `'standard'` and `'extended'`, and nothing else |

The table already holds every ingested corpus document by the time your migration runs. A `NOT
NULL` column added to a populated table needs a value for each existing row, and the default is
what supplies it.

"Permitted values" is a database constraint, not a convention: the checks ask the database to store
`'archive'` and require it to refuse. A plain text column constrains nothing.

## What is supplied

| Path | What it is |
|---|---|
| `alembic.ini` | Tool configuration. Points at `migrations/`, commits no database URL. |
| `migrations/env.py` | The migration environment. Reads `COLDLINE_DATABASE_URL` from the container. |
| `migrations/script.py.mako` | The template every generated revision is rendered from. |
| `migrations/versions/0001baseline_*.py` | The empty baseline revision your migration chains from. |
| `infra/postgres/004_migration_baseline.sql` | Creates `alembic_version` and stamps the baseline. |

The `exceptions`, `documents`, `chunks`, and `idempotency_claims` tables are created by the
initializer from explicit SQL under `infra/postgres/`, before any migration runs. That is why the
baseline revision is empty: it means "the schema as initialized", and it is the point a rollback
stops at.

Autogeneration is deliberately unavailable. This schema is owned by explicit SQL rather than by an
ORM, so `alembic revision --autogenerate` has no model metadata to diff against. You write
`upgrade()` and `downgrade()` yourself, which is also what makes the rollback real rather than
inferred.

## Commands

```shell
poe migrate-new -m "add retention class"   # generate an empty revision (no database needed)
poe start               # rebuild the image so it carries your revision
poe migrate             # alembic upgrade head, inside the API container
poe migrate-current     # the revision the database is stamped at
poe migrate-down        # alembic downgrade -1
poe migration           # start, ingest, then this Task's checks
```

Your migration ships inside the API image. `poe migrate` runs Alembic in the container, so rebuild
with `poe start` after you edit the revision file, or the container will still hold the previous
version of it. `poe migration` and `poe verify` both begin with `poe start` for that reason.

## The answer

```yaml
answers:
  migration_revision_id: ""
```

The revision identifier Alembic generated. Read it from the generated file name (the part before
the first underscore), from the `revision: str = "..."` line inside the file, or from
`poe migrate-current` once you have applied it. `0001baseline` is the supplied baseline and is not
an accepted answer.

Every student's identifier is different, because Alembic generates it. The checks look up the
revision that actually exists in your repository and the revision your database is stamped at, and
require both to be the one you recorded.

## What the checks verify

| Check | What it looks at |
|---|---|
| `test_exactly_one_reversible_migration_is_authored` | `migrations/versions/`: one authored revision, matching the recorded identifier, chained to the baseline, with statements in both directions |
| `test_forward_migration_creates_the_required_column` | `information_schema.columns` after `upgrade head`, and `alembic_version` |
| `test_the_permitted_values_are_enforced_by_the_database` | What PostgreSQL accepts and refuses for `retention_class` |
| `test_pre_existing_rows_receive_the_default` | Every corpus row already in `documents` carries `'standard'` |
| `test_the_application_still_works_against_the_migrated_schema` | The document API and the retrieval API, over HTTP |
| `test_rollback_reverses_the_schema_and_preserves_the_data` | The column is gone, the stamp is back at the baseline, and the document and chunk counts are unchanged |
| `test_the_forward_rollback_forward_cycle_is_repeatable` | Two full down-and-up cycles leave the same schema and the same rows |

The last two are the reason `downgrade()` cannot be left empty and cannot be written as "drop the
table and recreate it". Dropping `documents` takes its rows and its chunks with it, and the counts
are compared across the rollback precisely to catch that.

## Student-editable paths

- anything you add under `migrations/versions/`
- anything you add under `tests/student/`
- `submission.yaml`

`alembic.ini`, `migrations/env.py`, `migrations/script.py.mako`, the baseline revision, and
`infra/postgres/` are protected. So is the application source: this Task changes the schema, not
the code that reads it.

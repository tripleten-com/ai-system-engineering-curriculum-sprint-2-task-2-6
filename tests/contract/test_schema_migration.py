"""Coldline.

===================

File:              tests/contract/test_schema_migration.py
Component:         Contract tests — Schema migration
Purpose:           Verify the forward schema, its data effect, the application, and rollback.
Interacts With:    Alembic, PostgreSQL, the running API
Sprint/Task:       Sprint 2 — Project 2 / Task 2.6
Concepts:          Reversible migrations, data preservation, database-state verification
Tools:             Python 3.12, pytest, Docker Compose, httpx
"""

import re
import subprocess
from pathlib import Path

import httpx
import pytest
import yaml

from tests.runtime_config import host_port

TASK_ROOT = Path(__file__).resolve().parents[2]
VERSIONS = TASK_ROOT / "migrations/versions"
# `assessed`: a fresh starter has no migration and is supposed to fail these.
# `runtime`: every check reads the real database through the running stack.
pytestmark = [pytest.mark.runtime, pytest.mark.assessed]

COMPOSE = (
    "docker",
    "compose",
    "--profile",
    "observability",
    "--profile",
    "localstack",
)
BASELINE_REVISION = "0001baseline"

# The required change, stated once. The contract document, the README, and these
# assertions all describe the same column, so they cannot drift apart silently.
REQUIRED_TABLE = "documents"
REQUIRED_COLUMN = "retention_class"
REQUIRED_DEFAULT = "standard"
PERMITTED_VALUE = "extended"
REJECTED_VALUE = "archive"


def _api() -> str:
    """Return the API base URL, honoring the documented host-port override."""
    return f"http://localhost:{host_port('COLDLINE_API_HOST_PORT', 8000)}"


def _run_psql(statement: str) -> subprocess.CompletedProcess[str]:
    """Run one statement through psql, stopping on the first error."""
    return subprocess.run(
        [
            *COMPOSE,
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "coldline",
            "-d",
            "coldline",
            "-v",
            "ON_ERROR_STOP=1",
            "-tAc",
            statement,
        ],
        cwd=TASK_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _psql(statement: str) -> str:
    """Run one statement that must succeed and return its trimmed output."""
    result = _run_psql(statement)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


def _alembic(*arguments: str) -> subprocess.CompletedProcess[str]:
    """Run one Alembic command inside the API container."""
    return subprocess.run(
        [*COMPOSE, "exec", "-T", "api", "alembic", *arguments],
        cwd=TASK_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def _upgrade_to_head() -> None:
    """Apply every migration, failing with Alembic's own output when it cannot."""
    result = _alembic("upgrade", "head")
    assert result.returncode == 0, result.stdout + result.stderr


def recorded_revision() -> str:
    """Return the recorded revision identifier or fail with actionable guidance."""
    document = yaml.safe_load((TASK_ROOT / "submission.yaml").read_text(encoding="utf-8"))
    answers = document.get("answers") if isinstance(document, dict) else None
    recorded = answers.get("migration_revision_id", "") if isinstance(answers, dict) else ""
    if not isinstance(recorded, str) or not re.fullmatch(r"[0-9a-zA-Z_]{4,64}", recorded):
        pytest.fail(
            "answers.migration_revision_id must be the revision identifier Alembic generated "
            f"for your migration; found {recorded!r}"
        )
    if recorded == BASELINE_REVISION:
        pytest.fail(
            "answers.migration_revision_id names the supplied baseline revision. Record the "
            "identifier of the revision you generated."
        )
    return recorded


def _authored_revisions() -> dict[str, Path]:
    """Return every revision in the repository except the supplied baseline."""
    found: dict[str, Path] = {}
    for path in sorted(VERSIONS.glob("*.py")):
        if path.name.startswith("__"):
            continue
        match = re.search(
            r"""^revision: str = ["']([^"']+)["']""",
            path.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
        if match and match.group(1) != BASELINE_REVISION:
            found[match.group(1)] = path
    return found


def _current_revision() -> str:
    """Return the revision the database is stamped at."""
    return _psql("SELECT version_num FROM alembic_version")


def _corpus_counts() -> tuple[str, str]:
    """Return the ingested corpus document and chunk counts."""
    return (
        _psql("SELECT count(*) FROM documents WHERE document_id LIKE 'sop-%'"),
        _psql("SELECT count(*) FROM chunks WHERE document_id LIKE 'sop-%'"),
    )


def _column_facts() -> dict[str, str]:
    """Return the column's nullability and default, or an empty mapping when absent."""
    row = _psql(
        "SELECT is_nullable || '|' || coalesce(column_default, '') "
        "FROM information_schema.columns "
        f"WHERE table_name = '{REQUIRED_TABLE}' AND column_name = '{REQUIRED_COLUMN}'"
    )
    if not row:
        return {}
    nullable, _, default = row.partition("|")
    return {"is_nullable": nullable, "default": default}


def test_exactly_one_reversible_migration_is_authored() -> None:
    """One migration file, chained to the baseline, with both directions written."""
    recorded = recorded_revision()
    authored = _authored_revisions()
    assert authored, (
        "no migration revision is present under migrations/versions/ beyond the supplied "
        'baseline; generate one with `poe migrate-new -m "add retention class"`'
    )
    assert list(authored) == [recorded], (
        f"exactly one authored revision is expected, matching the recorded {recorded!r}; "
        f"found {sorted(authored)}"
    )

    text = authored[recorded].read_text(encoding="utf-8")
    chained = re.search(rf"""down_revision: str \| None = ["']{BASELINE_REVISION}["']""", text)
    assert chained is not None, (
        f"the migration must chain to the supplied baseline revision {BASELINE_REVISION!r}"
    )
    upgrade_body = text.split("def upgrade()", maxsplit=1)[1].split("def downgrade()")[0]
    downgrade_body = text.split("def downgrade()", maxsplit=1)[1]
    assert "op." in upgrade_body, "upgrade() applies no schema change"
    assert "op." in downgrade_body, (
        "downgrade() reverses nothing. A migration that cannot be rolled back is not "
        "reversible, and the rollback check below has nothing to verify."
    )


def test_forward_migration_creates_the_required_column() -> None:
    """Applying the migration must produce the required column, not just any column."""
    recorded = recorded_revision()
    _upgrade_to_head()

    stamped = _current_revision()
    assert stamped == recorded, (
        f"the database is stamped at {stamped!r}, not at the recorded {recorded!r}"
    )
    facts = _column_facts()
    assert facts, f"{REQUIRED_TABLE}.{REQUIRED_COLUMN} does not exist after the forward migration"
    assert facts["is_nullable"] == "NO", (
        f"{REQUIRED_COLUMN} must be NOT NULL; the default is what makes that possible on a "
        "table that already holds rows"
    )
    assert f"'{REQUIRED_DEFAULT}'" in facts["default"], (
        f"{REQUIRED_COLUMN} must default to {REQUIRED_DEFAULT!r}; found {facts['default']!r}"
    )


def test_the_permitted_values_are_enforced_by_the_database() -> None:
    """The constraint is verified by what the database accepts, not by reading its text."""
    recorded_revision()
    _upgrade_to_head()

    permitted = _run_psql(
        f"BEGIN; UPDATE {REQUIRED_TABLE} SET {REQUIRED_COLUMN} = '{PERMITTED_VALUE}'; ROLLBACK;"
    )
    assert permitted.returncode == 0, (
        f"the database rejected the permitted value {PERMITTED_VALUE!r}: "
        + permitted.stdout
        + permitted.stderr
    )

    # Both probes roll back. An unconstrained column would otherwise let this
    # check rewrite every row and fail the later ones for the wrong reason.
    rejected = _run_psql(
        f"BEGIN; UPDATE {REQUIRED_TABLE} SET {REQUIRED_COLUMN} = '{REJECTED_VALUE}'; ROLLBACK;"
    )
    assert rejected.returncode != 0, (
        f"the database accepted {REJECTED_VALUE!r}. {REQUIRED_COLUMN} must be constrained to "
        f"{REQUIRED_DEFAULT!r} and {PERMITTED_VALUE!r}; a plain text column with no check "
        "constrains nothing."
    )
    assert (
        _psql(f"SELECT count(*) FROM {REQUIRED_TABLE} WHERE {REQUIRED_COLUMN} = '{REJECTED_VALUE}'")
        == "0"
    ), "a rejected value was nevertheless stored"


def test_pre_existing_rows_receive_the_default() -> None:
    """A NOT NULL column added to a populated table needs every existing row to have a value."""
    recorded_revision()
    _upgrade_to_head()

    documents, _ = _corpus_counts()
    assert documents != "0", "the ingested corpus is missing; run `poe ingest`"
    defaulted = _psql(
        f"SELECT count(*) FROM {REQUIRED_TABLE} "
        f"WHERE document_id LIKE 'sop-%' AND {REQUIRED_COLUMN} = '{REQUIRED_DEFAULT}'"
    )
    assert defaulted == documents, (
        f"{defaulted} of {documents} pre-existing corpus rows carry the default"
    )


def test_the_application_still_works_against_the_migrated_schema() -> None:
    """A schema change that breaks the running application is not a successful migration."""
    recorded_revision()
    _upgrade_to_head()

    with httpx.Client(timeout=30.0) as client:
        listing = client.get(f"{_api()}/api/v1/documents", params={"tenant_id": "tenant-northwind"})
        search = client.post(
            f"{_api()}/api/v1/retrieval/search",
            json={
                "query_id": "q-migration-regression",
                "text": "container pre-cool fault before loading",
                "authorization": {"tenant_id": "tenant-northwind", "clearance": "standard"},
            },
        )
    assert listing.status_code == 200, listing.text
    assert listing.json()["documents"], "the document API returned nothing after the migration"
    assert search.status_code == 200, search.text
    assert search.json()["results"], "retrieval returned nothing after the migration"


def test_rollback_reverses_the_schema_and_preserves_the_data() -> None:
    """Downgrade must remove exactly what upgrade added and touch no row."""
    recorded = recorded_revision()
    _upgrade_to_head()
    before = _corpus_counts()
    assert before[0] != "0", "the ingested corpus is missing; run `poe ingest`"

    result = _alembic("downgrade", "-1")
    assert result.returncode == 0, result.stdout + result.stderr

    assert _column_facts() == {}, (
        f"{REQUIRED_TABLE}.{REQUIRED_COLUMN} still exists after the rollback"
    )
    stamped = _current_revision()
    assert stamped == BASELINE_REVISION, (
        f"the database is stamped at {stamped!r} after the rollback, not at the supplied "
        f"baseline {BASELINE_REVISION!r}"
    )
    after = _corpus_counts()
    assert after == before, (
        f"the rollback changed the data: {before} documents and chunks became {after}. A "
        "rollback that recreates a table instead of reversing the change loses rows."
    )

    # Leave the database where the remaining checks expect to find it.
    assert _alembic("upgrade", recorded).returncode == 0


def test_the_forward_rollback_forward_cycle_is_repeatable() -> None:
    """A migration usable in a deployment pipeline survives being run more than once."""
    recorded = recorded_revision()
    _upgrade_to_head()
    before = _corpus_counts()

    for cycle in range(2):
        assert _alembic("downgrade", "-1").returncode == 0, f"cycle {cycle}: downgrade failed"
        assert _column_facts() == {}, f"cycle {cycle}: the column survived the rollback"
        assert _alembic("upgrade", "head").returncode == 0, f"cycle {cycle}: re-upgrade failed"
        assert _column_facts(), f"cycle {cycle}: the column did not come back"

    assert _current_revision() == recorded
    assert _corpus_counts() == before, "the corpus changed across the migration cycles"

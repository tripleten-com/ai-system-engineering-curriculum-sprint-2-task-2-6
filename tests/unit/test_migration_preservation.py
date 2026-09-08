"""Coldline.

===================

File:              tests/unit/test_migration_preservation.py
Component:         Unit tests — Migration assessment
Purpose:           Reject value corruption even when migration row counts stay unchanged.
Interacts With:    Runtime schema-migration checks
Sprint/Task:       Sprint 2 — Project 2 / Task 2.6
Concepts:          Data preservation, reversible migrations, assessment regression
Tools:             Python 3.12, pytest
"""

import copy
import json
import subprocess

import pytest

from tests.contract import test_schema_migration as migration


def stored_data() -> dict:
    """Return rows with scalar, nested JSON, and chunk fields to preserve."""
    return {
        "documents": [
            {
                "document_id": "sop-test",
                "title": "Original title",
                "tenant_id": "tenant-test",
                "access_tier": "standard",
                "provenance": {"source": "original", "version": 1},
            }
        ],
        "chunks": [
            {
                "chunk_id": "chunk-test",
                "document_id": "sop-test",
                "text": "Original text",
                "embedding": "[0.25,0.75]",
            }
        ],
    }


@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
@pytest.mark.parametrize(
    ("table", "field", "replacement"),
    [
        ("documents", "title", "Corrupted title"),
        ("documents", "tenant_id", "another-tenant"),
        ("documents", "access_tier", "restricted"),
        ("documents", "provenance", {"source": "original", "version": 2}),
        ("chunks", "text", "Corrupted text"),
        ("chunks", "embedding", "[0.75,0.25]"),
        ("chunks", "document_id", "another-document"),
    ],
)
def test_same_count_value_corruption_fails(
    monkeypatch: pytest.MonkeyPatch, direction: str, table: str, field: str, replacement: object
) -> None:
    """Successful Alembic status and identical counts cannot conceal changed values."""
    before = stored_data()
    after = copy.deepcopy(before)
    after[table][0][field] = replacement
    assert {name: len(rows) for name, rows in before.items()} == {
        name: len(rows) for name, rows in after.items()
    }
    snapshots = iter((json.dumps(before), json.dumps(after)))
    monkeypatch.setattr(migration, "_psql", lambda _statement: next(snapshots))
    monkeypatch.setattr(
        migration, "_alembic", lambda *_args: subprocess.CompletedProcess([], 0, "", "")
    )
    with pytest.raises(AssertionError, match=f"{direction} .* changed stored {table} values"):
        if direction == "upgrade":
            migration._upgrade_to_head()
        else:
            migration._migrate_preserving_data("downgrade", "-1")


def test_only_the_intended_column_is_excluded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Adding or removing retention_class is allowed; other schema fields are retained."""
    before = stored_data()
    after = copy.deepcopy(before)
    after["documents"][0]["retention_class"] = "standard"
    snapshots = iter((json.dumps(before), json.dumps(after), json.dumps(before)))
    monkeypatch.setattr(migration, "_psql", lambda _statement: next(snapshots))
    baseline = migration._data_snapshot()
    assert baseline == migration._data_snapshot() == migration._data_snapshot()
    after["chunks"][0]["retention_class"] = "unexpected"
    monkeypatch.setattr(migration, "_psql", lambda _statement: json.dumps(after))
    with pytest.raises(AssertionError, match="changed stored chunks values"):
        migration._assert_data_preserved(baseline, migration._data_snapshot(), "upgrade head")


def test_snapshot_is_independent_of_row_and_json_key_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """Physical row order and JSON object serialization order do not change data."""
    before = stored_data()
    before["documents"].append({"document_id": "another-document", "title": "Another title"})
    after = {
        table: [dict(reversed(list(row.items()))) for row in reversed(rows)]
        for table, rows in before.items()
    }
    snapshots = iter((json.dumps(before), json.dumps(after)))
    monkeypatch.setattr(migration, "_psql", lambda _statement: next(snapshots))
    assert migration._data_snapshot() == migration._data_snapshot()


def test_cycle_rejects_corruption_before_a_later_step_can_undo_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each cycle half is checked even if the inverse operation would restore the data."""
    data = stored_data()
    calls = []

    def alembic(*arguments: str) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        data["documents"][0]["title"] = (
            "Corrupted title" if arguments[0] == "downgrade" else "Original title"
        )
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(migration, "recorded_revision", lambda: "testrevision")
    monkeypatch.setattr(migration, "_psql", lambda _statement: json.dumps(data))
    monkeypatch.setattr(migration, "_alembic", alembic)
    with pytest.raises(AssertionError, match="downgrade .* changed stored documents values"):
        migration.test_the_forward_rollback_forward_cycle_is_repeatable()
    assert calls == [("upgrade", "head"), ("downgrade", "-1")]

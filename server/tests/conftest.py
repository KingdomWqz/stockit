"""Shared test fixtures.

Replaces the previous FakeClient/PostgREST query-builder fake with a real
in-memory SQLite database. The fixture executes ``server/schema_sqlite.sql``
to create the three tables, then monkeypatches ``db_client.get_client`` to
return the test connection — so all behaviour-level tests run against a real
database without network or Supabase DSL.
"""

import os

import pytest

import db_client

_SCHEMA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "schema_sqlite.sql",
)


@pytest.fixture
def fake_db(monkeypatch):
    """Return a real in-memory SQLite connection backed by the project schema.

    Kept under the historical name ``fake_db`` so existing tests and their
    seed/inspect helpers keep working; it now returns a ``sqlite3.Connection``
    with ``row_factory = sqlite3.Row`` instead of a fake client.

    Tests seed/inspect rows via plain SQL rather than the removed query-builder
    DSL. ``db_client.get_client`` is patched to return this connection.
    """
    import sqlite3

    con = sqlite3.connect(":memory:", check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    with open(_SCHEMA_PATH) as f:
        con.executescript(f.read())
    con.commit()

    monkeypatch.setattr(db_client, "get_client", lambda: con)
    try:
        yield con
    finally:
        con.close()


@pytest.fixture
def client():
    """FastAPI TestClient bound to the real app (no live server)."""
    from fastapi.testclient import TestClient
    from main import app

    return TestClient(app)

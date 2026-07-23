"""Shared test fixtures.

The Supabase client is mocked at the ``db_client.get_client`` seam with an
in-memory fake that re-implements the small subset of the query-builder DSL
Stockit uses (select / eq / in_ / or_ / limit / upsert / update). This lets
behaviour-level tests run without a real database or network.
"""

import time

import jwt
import pytest

import db_client
from auth import SECRET


class _Response:
    def __init__(self, data):
        self.data = data


def _match_pattern(value, pattern, case_insensitive):
    v = str(value)
    p = pattern
    if case_insensitive:
        v, p = v.lower(), p.lower()
    starts, ends = p.startswith("%"), p.endswith("%")
    core = p.strip("%")
    if starts and ends:
        return core in v
    if starts:
        return v.endswith(core)
    if ends:
        return v.startswith(core)
    return v == core


class _QueryBuilder:
    def __init__(self, rows):
        self._rows = rows
        self._cols = ("*",)
        self._and_filters = []
        self._or_filters = []
        self._limit = None
        self._mode = "select"
        self._payload = None

    def select(self, *cols):
        self._mode = "select"
        if len(cols) == 1 and isinstance(cols[0], str) and "," in cols[0]:
            self._cols = tuple(c.strip() for c in cols[0].split(","))
        else:
            self._cols = cols or ("*",)
        return self

    def eq(self, column, value):
        self._and_filters.append(("eq", column, value))
        return self

    def in_(self, column, values):
        self._and_filters.append(("in", column, list(values)))
        return self

    def or_(self, query):
        for clause in query.split(","):
            col, op, pattern = clause.split(".", 2)
            self._or_filters.append((col.strip(), op.strip(), pattern))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def upsert(self, records, on_conflict=None):
        self._mode = "upsert"
        self._payload = records
        return self

    def update(self, payload):
        self._mode = "update"
        self._payload = payload
        return self

    def _matches(self, row):
        for op, column, value in self._and_filters:
            if op == "eq" and row.get(column) != value:
                return False
            if op == "in" and row.get(column) not in value:
                return False
        if not self._or_filters:
            return True
        for col, op, pattern in self._or_filters:
            if op == "ilike" and _match_pattern(row.get(col, ""), pattern, True):
                return True
            if op == "like" and _match_pattern(row.get(col, ""), pattern, False):
                return True
        return False

    def execute(self):
        matched = [r for r in self._rows if self._matches(r)]
        if self._mode == "select":
            if self._limit is not None:
                matched = matched[: self._limit]
            if self._cols == ("*",):
                return _Response([dict(r) for r in matched])
            return _Response([{c: r.get(c) for c in self._cols} for r in matched])
        if self._mode == "upsert":
            for rec in self._payload:
                existing = next(
                    (r for r in self._rows if r.get("code") == rec.get("code")), None
                )
                if existing is None:
                    self._rows.append(dict(rec))
                else:
                    existing.update(rec)
            return _Response(self._payload)
        if self._mode == "update":
            for r in matched:
                r.update(self._payload)
            return _Response([dict(r) for r in matched])
        return _Response(None)


class FakeClient:
    def __init__(self):
        self.tables = {"stocks": [], "stock_daily_data": []}

    def table(self, name):
        return _QueryBuilder(self.tables[name])

    def rpc(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("rpc not expected in these tests")


@pytest.fixture
def fake_db(monkeypatch):
    """Replace ``db_client.get_client`` with an in-memory fake and return it."""
    client = FakeClient()
    monkeypatch.setattr(db_client, "get_client", lambda: client)
    return client


def make_token(username="admin", user_id=1, exp_delta=86400 * 7):
    return jwt.encode(
        {"user_id": user_id, "username": username, "exp": int(time.time()) + exp_delta},
        SECRET,
        algorithm="HS256",
    )


@pytest.fixture
def auth_headers():
    return {"Authorization": f"Bearer {make_token()}"}

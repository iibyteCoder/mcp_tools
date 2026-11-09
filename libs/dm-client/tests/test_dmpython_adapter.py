"""Unit tests for the dmPython cursor, connection and factory adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING

import dmPython
import pytest

from dm_client.adapters.dmpython.connection import DmpythonConnection, DmpythonDriverFactory
from dm_client.adapters.dmpython.cursor import DmpythonCursor
from dm_client.domain.configuration import DmConnectionConfig, SecretValue
from dm_client.domain.errors import PermissionDeniedError, QueryError
from dm_client.domain.values import SchemaName

if TYPE_CHECKING:
    from collections.abc import Sequence


class FakeRawCursor:
    def __init__(
        self,
        *,
        description: Sequence[object] | None = None,
        rows: Sequence[Sequence[object]] = (),
        rowcount: int = 0,
    ) -> None:
        self.description = description
        self.rows = rows
        self.rowcount = rowcount
        self.executed: list[tuple[str, Sequence[object] | None]] = []
        self.closed = False
        self.fail_with: BaseException | None = None

    def execute(self, sql: str, parameters: Sequence[object] | None = None) -> object:
        if self.fail_with is not None:
            raise self.fail_with
        self.executed.append((sql, parameters))
        return None

    def fetchmany(self, size: int) -> Sequence[Sequence[object]]:
        if self.fail_with is not None:
            raise self.fail_with
        return self.rows[:size]

    def close(self) -> object:
        self.closed = True
        return None


class FakeRawConnection:
    def __init__(self, cursor: FakeRawCursor | None = None) -> None:
        self.user = "APP"
        self.server_version = "8.1.4.80"
        self.current_schema = "APP"
        self.str_case_sensitive = 0
        self.max_identifier_length = 128
        self._cursor = cursor or FakeRawCursor()
        self.explained: list[str] = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self.fail_with: BaseException | None = None

    def cursor(self) -> FakeRawCursor:
        if self.fail_with is not None:
            raise self.fail_with
        return self._cursor

    def explain(self, sql: str) -> object:
        if self.fail_with is not None:
            raise self.fail_with
        self.explained.append(sql)
        return "plan text"

    def commit(self) -> object:
        if self.fail_with is not None:
            raise self.fail_with
        self.commits += 1
        return None

    def rollback(self) -> object:
        if self.fail_with is not None:
            raise self.fail_with
        self.rollbacks += 1
        return None

    def close(self) -> object:
        self.closed = True
        return None


def config(**overrides: object) -> DmConnectionConfig:
    values: dict[str, object] = {
        "host": "127.0.0.1",
        "port": 15237,
        "user": "APP",
        "password": SecretValue(_value="secret"),
        "connect_timeout_seconds": 5.0,
        "query_timeout_seconds": 30.0,
    }
    values.update(overrides)
    return DmConnectionConfig(**values)  # type: ignore[arg-type]


def test_cursor_description_converts_seven_tuples() -> None:
    raw = FakeRawCursor(
        description=[
            ("N", int, 10, 10, 10, 0, 0),
            ("S", str, 10, 10, 10, 0, None),
        ]
    )
    cursor = DmpythonCursor(raw)

    columns = cursor.description

    assert columns is not None
    assert columns[0].name == "N"
    assert columns[0].type_name == "int"
    assert columns[0].nullable is False
    assert columns[1].name == "S"
    assert columns[1].nullable is True


def test_cursor_execute_without_parameters_uses_single_argument() -> None:
    raw = FakeRawCursor()
    cursor = DmpythonCursor(raw)

    cursor.execute("SELECT 1 FROM DUAL")

    assert raw.executed == [("SELECT 1 FROM DUAL", None)]


def test_cursor_execute_with_parameters_forwards_qmark_values() -> None:
    raw = FakeRawCursor()
    cursor = DmpythonCursor(raw)

    cursor.execute("SELECT ? FROM DUAL", (7,))

    assert raw.executed == [("SELECT ? FROM DUAL", (7,))]


def test_cursor_fetchmany_adapts_values() -> None:
    raw = FakeRawCursor(rows=[(1, "x", None), (2, "y", None)])
    cursor = DmpythonCursor(raw)

    rows = cursor.fetchmany(2)

    assert rows == ((1, "x", None), (2, "y", None))


def test_cursor_rowcount_and_close() -> None:
    raw = FakeRawCursor(rowcount=3)
    cursor = DmpythonCursor(raw)

    assert cursor.rowcount == 3
    cursor.close()

    assert raw.closed is True


def test_cursor_translates_execution_errors() -> None:
    raw = FakeRawCursor()
    raw.fail_with = RuntimeError("[CODE:-2007] syntax error")
    cursor = DmpythonCursor(raw)

    with pytest.raises(QueryError):
        cursor.execute("SELECT broken FROM")


def test_connection_exposes_typed_properties_and_operations() -> None:
    raw = FakeRawConnection()
    connection = DmpythonConnection(raw)

    assert connection.user == "APP"
    assert connection.server_version == "8.1.4.80"
    assert connection.current_schema == "APP"
    assert connection.str_case_sensitive is False
    assert connection.max_identifier_length == 128
    assert connection.explain("SELECT 1 FROM DUAL") == "plan text"

    cursor = connection.cursor()
    assert isinstance(cursor, DmpythonCursor)
    connection.commit()
    connection.rollback()
    connection.close()

    assert raw.explained == ["SELECT 1 FROM DUAL"]
    assert raw.commits == 1
    assert raw.rollbacks == 1
    assert raw.closed is True


def test_factory_passes_millisecond_login_timeout_and_omits_absent_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = FakeRawConnection()
    captured: dict[str, object] = {}

    def fake_connect(**kwargs: object) -> FakeRawConnection:
        captured.update(kwargs)
        return raw

    monkeypatch.setattr(dmPython, "connect", fake_connect)
    factory = DmpythonDriverFactory()

    connection = factory.connect(config())

    assert isinstance(connection, DmpythonConnection)
    assert captured["server"] == "127.0.0.1"
    assert captured["port"] == 15237
    assert captured["autoCommit"] is False
    assert captured["login_timeout"] == 5000
    assert captured["connection_timeout"] == 30
    assert isinstance(captured["connection_timeout"], int)
    assert "schema" not in captured


def test_factory_forwards_requested_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_connect(**kwargs: object) -> FakeRawConnection:
        captured.update(kwargs)
        return FakeRawConnection()

    monkeypatch.setattr(dmPython, "connect", fake_connect)
    factory = DmpythonDriverFactory()

    factory.connect(config(schema=SchemaName(value="APP")))

    assert captured["schema"] == "APP"


def test_factory_translates_connect_errors_without_leaking_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_connect(**kwargs: object) -> FakeRawConnection:
        raise RuntimeError("[CODE:-5504] no privilege for secret")

    monkeypatch.setattr(dmPython, "connect", fake_connect)
    factory = DmpythonDriverFactory()

    with pytest.raises(PermissionDeniedError) as caught:
        factory.connect(config())

    assert "secret" not in str(caught.value)
    assert "<redacted>" in str(caught.value)

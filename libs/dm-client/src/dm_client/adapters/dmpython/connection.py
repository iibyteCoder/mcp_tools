"""dmPython connection adapter and the concrete driver factory."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Protocol, cast

from dm_client.adapters.dmpython.cursor import DmpythonCursor
from dm_client.adapters.dmpython.errors import translate_configuration_error, translate_driver_error

if TYPE_CHECKING:
    from dm_client.adapters.dmpython.cursor import _RawCursor
    from dm_client.domain.configuration import DmConnectionConfig
    from dm_client.ports.driver import DmConnection


class _RawConnection(Protocol):
    """Minimal structural surface exposed by a dmPython connection."""

    @property
    def user(self) -> object: ...

    @property
    def server_version(self) -> object: ...

    @property
    def current_schema(self) -> object: ...

    @property
    def str_case_sensitive(self) -> object: ...

    @property
    def max_identifier_length(self) -> object: ...

    def cursor(self) -> _RawCursor: ...

    def explain(self, sql: str) -> object: ...

    def commit(self) -> object: ...

    def rollback(self) -> object: ...

    def close(self) -> object: ...


class _DmPythonModule(Protocol):
    """Structural surface of the dmPython module used by the factory."""

    def connect(self, **kwargs: object) -> _RawConnection: ...


class DmpythonConnection:
    """Expose one dmPython connection through the typed driver port."""

    def __init__(self, raw_connection: _RawConnection) -> None:
        self._raw_connection = raw_connection

    @property
    def user(self) -> str:
        value = self._raw_connection.user
        return "" if value is None else str(value)

    @property
    def server_version(self) -> str:
        value = self._raw_connection.server_version
        return "" if value is None else str(value)

    @property
    def current_schema(self) -> str:
        value = self._raw_connection.current_schema
        return "" if value is None else str(value)

    @property
    def str_case_sensitive(self) -> bool:
        return bool(self._raw_connection.str_case_sensitive)

    @property
    def max_identifier_length(self) -> int:
        value = self._raw_connection.max_identifier_length
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        return 0

    def cursor(self) -> DmpythonCursor:
        try:
            return DmpythonCursor(self._raw_connection.cursor())
        except Exception as exc:
            raise translate_driver_error(exc) from exc

    def explain(self, sql: str) -> str:
        try:
            return str(self._raw_connection.explain(sql))
        except Exception as exc:
            raise translate_driver_error(exc, sql=sql) from exc

    def commit(self) -> None:
        try:
            self._raw_connection.commit()
        except Exception as exc:
            raise translate_driver_error(exc) from exc

    def rollback(self) -> None:
        try:
            self._raw_connection.rollback()
        except Exception as exc:
            raise translate_driver_error(exc) from exc

    def close(self) -> None:
        try:
            self._raw_connection.close()
        except Exception as exc:
            raise translate_driver_error(exc) from exc


class DmpythonDriverFactory:
    """Create one non-pooled dmPython connection for a resolved target."""

    def connect(self, config: DmConnectionConfig) -> DmConnection:
        try:
            import dmPython

            module = cast("_DmPythonModule", dmPython)
            arguments: dict[str, object] = {
                "user": config.user,
                "password": config.password.reveal(),
                "server": config.host,
                "port": config.port,
                "autoCommit": False,
                "login_timeout": int(config.connect_timeout_seconds * 1000),
                "connection_timeout": _execution_timeout_seconds(config.query_timeout_seconds),
            }
            if config.schema is not None:
                arguments["schema"] = config.schema.value
            raw_connection = module.connect(**arguments)
        except Exception as exc:
            raise translate_configuration_error(exc, secrets=(config.password.reveal(),)) from exc
        return DmpythonConnection(raw_connection)


def _execution_timeout_seconds(value: float) -> int:
    """dmPython accepts only whole seconds for ``connection_timeout``."""

    if value <= 0:
        return 0
    return math.ceil(value)


__all__ = ["DmpythonConnection", "DmpythonDriverFactory"]

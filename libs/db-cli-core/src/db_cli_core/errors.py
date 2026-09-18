"""Stable CLI errors, classified by exception types and driver codes."""

from dataclasses import dataclass
from typing import Any

from mcp_base.types import ToolResult, ToolStatus


class ProfileNotFoundError(ValueError):
    """The requested named configuration does not exist."""


@dataclass
class CliError(ToolResult):
    code: str = "EXECUTION_FAILED"
    hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        payload["code"] = self.code
        if self.hint:
            payload["hint"] = self.hint
        return payload


def error_result(exc: Exception) -> CliError:
    chain: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and current not in chain:
        chain.append(current)
        current = current.__cause__ or current.__context__

    # Drivers are optional here: each database CLI installs its own driver.
    try:
        from redis.exceptions import AuthenticationError
        from redis.exceptions import ConnectionError as RedisConnectionError
        from redis.exceptions import TimeoutError as RedisTimeoutError
    except ImportError:
        auth_types: tuple[type[BaseException], ...] = ()
        timeout_types: tuple[type[BaseException], ...] = (TimeoutError,)
        connection_types: tuple[type[BaseException], ...] = (ConnectionError,)
    else:
        auth_types = (AuthenticationError,)
        timeout_types = (TimeoutError, RedisTimeoutError)
        connection_types = (ConnectionError, RedisConnectionError)
    try:
        from pymysql.err import MySQLError  # type: ignore[import-untyped]
    except ImportError:
        mysql_errors: tuple[type[BaseException], ...] = ()
    else:
        mysql_errors = (MySQLError,)

    code, message, hint = "EXECUTION_FAILED", str(exc), ""
    if any(isinstance(item, ProfileNotFoundError) for item in chain):
        code, hint = "PROFILE_NOT_FOUND", "使用 profile list 查看已有配置"
    elif any(
        isinstance(item, auth_types)
        or (isinstance(item, mysql_errors) and item.args and item.args[0] in (1044, 1045, 1698))
        for item in chain
    ):
        code, message, hint = "AUTH_FAILED", "认证或数据库访问被拒绝", "检查该配置的用户名、密码和权限"
    elif any(isinstance(item, timeout_types) for item in chain):
        code, message, hint = "TIMEOUT", "操作超时", "写操作可能已经生效, 核实结果后再决定是否重试"
    elif any(
        isinstance(item, connection_types)
        or (isinstance(item, mysql_errors) and item.args and item.args[0] in (2002, 2003, 2006, 2013))
        for item in chain
    ):
        code, hint = "CONNECTION_FAILED", "检查该配置的地址、端口和服务状态"
    elif isinstance(exc, (ValueError, TypeError)):
        code = "INVALID_ARGUMENT"
    return CliError(status=ToolStatus.ERROR, message=message, code=code, hint=hint)

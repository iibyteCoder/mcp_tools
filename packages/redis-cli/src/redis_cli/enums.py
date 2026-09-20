"""Enums shared across domain, application and presentation layers."""

from enum import Enum


class ErrorCode(str, Enum):
    """Stable machine-readable CLI error categories."""

    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    PROFILE_NOT_FOUND = "PROFILE_NOT_FOUND"
    PROFILE_CONFLICT = "PROFILE_CONFLICT"
    PROFILE_REGISTRY = "PROFILE_REGISTRY_ERROR"
    SECRET_STORE = "SECRET_STORE_ERROR"
    AUTH_FAILED = "AUTH_FAILED"
    CONNECTION_FAILED = "CONNECTION_FAILED"
    TIMEOUT = "TIMEOUT"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class RegistrySchema(str, Enum):
    """Persisted profile registry schemas."""

    REDIS_CONNECTIONS = "db-cli.redis-connections"


class ResultStatus(str, Enum):
    """Top-level JSON result status."""

    SUCCESS = "success"
    ERROR = "error"


class RedisKeyType(str, Enum):
    """Redis native key types supported by inspection commands."""

    STRING = "string"
    LIST = "list"
    SET = "set"
    ZSET = "zset"
    HASH = "hash"
    STREAM = "stream"
    JSON = "ReJSON-RL"
    NONE = "none"
    UNKNOWN = "unknown"


class RedisCommand(str, Enum):
    """Redis commands exposed by the typed CLI command groups."""

    APPEND = "APPEND"
    DEL = "DEL"
    EXISTS = "EXISTS"
    EXPIRE = "EXPIRE"
    GET = "GET"
    HDEL = "HDEL"
    HGET = "HGET"
    HGETALL = "HGETALL"
    HEXISTS = "HEXISTS"
    HKEYS = "HKEYS"
    HLEN = "HLEN"
    HSET = "HSET"
    HVALS = "HVALS"
    INCRBY = "INCRBY"
    LINDEX = "LINDEX"
    LLEN = "LLEN"
    LPOP = "LPOP"
    LPUSH = "LPUSH"
    LRANGE = "LRANGE"
    LTRIM = "LTRIM"
    MGET = "MGET"
    MSET = "MSET"
    PERSIST = "PERSIST"
    RANDOMKEY = "RANDOMKEY"
    RENAME = "RENAME"
    RPOP = "RPOP"
    RPUSH = "RPUSH"
    SADD = "SADD"
    SCARD = "SCARD"
    SISMEMBER = "SISMEMBER"
    SMEMBERS = "SMEMBERS"
    SREM = "SREM"
    SET = "SET"
    STRLEN = "STRLEN"
    TTL = "TTL"
    TYPE = "TYPE"
    ZADD = "ZADD"
    ZCARD = "ZCARD"
    ZRANGE = "ZRANGE"
    ZRANK = "ZRANK"
    ZREM = "ZREM"
    ZREVRANGE = "ZREVRANGE"
    ZREVRANK = "ZREVRANK"
    ZSCORE = "ZSCORE"


class RedisUrlScheme(str, Enum):
    """Supported Redis URL schemes."""

    REDIS = "redis"
    REDISS = "rediss"

    @property
    def tls(self) -> bool:
        return self is RedisUrlScheme.REDISS


class ProfileSelectionSource(str, Enum):
    """Where the active profile came from."""

    EXPLICIT = "explicit"
    DIRECTORY = "directory"
    DEFAULTS = "defaults"


__all__ = [
    "ErrorCode",
    "ProfileSelectionSource",
    "RedisCommand",
    "RedisKeyType",
    "RedisUrlScheme",
    "RegistrySchema",
    "ResultStatus",
]

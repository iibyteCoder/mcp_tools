"""Enums shared across domain, application and presentation layers."""

from enum import Enum


class ErrorCode(str, Enum):
    """Stable machine-readable CLI error categories."""

    INVALID_ARGUMENT = "invalid_argument"
    PROFILE_NOT_FOUND = "profile_not_found"
    PROFILE_CONFLICT = "profile_conflict"
    PROFILE_REGISTRY = "profile_registry"
    SECRET_STORE = "secret_store"
    AUTH_FAILED = "auth_failed"
    CONNECTION_FAILED = "connection_failed"
    TIMEOUT = "timeout"
    EXECUTION_FAILED = "execution_failed"
    CANCELLED = "cancelled"
    INTERNAL_ERROR = "internal_error"


class RegistrySchema(str, Enum):
    """Persisted profile registry schemas."""

    REDIS_CONNECTIONS = "db-cli.redis-connections"


class CommandGroup(str, Enum):
    """Top-level command groups reported in envelope metadata."""

    PROFILE = "profile"
    CONNECTION = "connection"
    SERVER = "server"
    KEY = "key"
    STRING = "string"
    HASH = "hash"
    LIST = "list"
    SET = "set"
    ZSET = "zset"
    SKILL = "skill"


class OutputMode(str, Enum):
    """Presentation modes reported in envelope metadata."""

    JSON = "json"


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
    "CommandGroup",
    "ErrorCode",
    "OutputMode",
    "ProfileSelectionSource",
    "RedisCommand",
    "RedisKeyType",
    "RedisUrlScheme",
    "RegistrySchema",
]

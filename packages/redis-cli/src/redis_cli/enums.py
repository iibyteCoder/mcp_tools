"""Redis command and application identifiers."""

from enum import Enum


class RedisApplication(str, Enum):
    NAME = "db-redis"
    HISTORY_FILE = ".db-redis-history"
    USE_COMMAND = "use"


class RedisCommandGroup(str, Enum):
    CONNECTION = "connection"
    KEY = "key"
    STRING = "string"
    HASH = "hash"
    LIST = "list"
    SET = "set"
    ZSET = "zset"
    SERVER = "server"


class RedisConnectionCommand(str, Enum):
    CONNECT = "redis_connect"
    DISCONNECT = "redis_disconnect"
    STATUS = "redis_status"


class RedisKeyCommand(str, Enum):
    KEYS = "redis_keys"
    EXISTS = "redis_exists"
    TYPE = "redis_type"
    TTL = "redis_ttl"
    EXPIRE = "redis_expire"
    PERSIST = "redis_persist"
    RENAME = "redis_rename"
    DELETE = "redis_delete"
    RANDOMKEY = "redis_randomkey"


class RedisStringCommand(str, Enum):
    GET = "redis_get"
    SET = "redis_set"
    MGET = "redis_mget"
    MSET = "redis_mset"
    INCR = "redis_incr"
    APPEND = "redis_append"
    STRLEN = "redis_strlen"


class RedisHashCommand(str, Enum):
    HGET = "redis_hget"
    HSET = "redis_hset"
    HGETALL = "redis_hgetall"
    HDEL = "redis_hdel"
    HEXISTS = "redis_hexists"
    HKEYS = "redis_hkeys"
    HVALS = "redis_hvals"
    HLEN = "redis_hlen"


class RedisListCommand(str, Enum):
    LPUSH = "redis_lpush"
    RPUSH = "redis_rpush"
    LPOP = "redis_lpop"
    RPOP = "redis_rpop"
    LRANGE = "redis_lrange"
    LLEN = "redis_llen"
    LINDEX = "redis_lindex"
    LTRIM = "redis_ltrim"


class RedisSetCommand(str, Enum):
    SADD = "redis_sadd"
    SREM = "redis_srem"
    SMEMBERS = "redis_smembers"
    SCARD = "redis_scard"
    SISMEMBER = "redis_sismember"


class RedisSortedSetCommand(str, Enum):
    ZADD = "redis_zadd"
    ZREM = "redis_zrem"
    ZRANGE = "redis_zrange"
    ZREVRANGE = "redis_zrevrange"
    ZCARD = "redis_zcard"
    ZSCORE = "redis_zscore"
    ZRANK = "redis_zrank"
    ZREVRANK = "redis_zrevrank"


class RedisServerCommand(str, Enum):
    INFO = "redis_info"
    DBSIZE = "redis_dbsize"
    PING = "redis_ping"
    FLUSHDB = "redis_flushdb"
    PIPELINE = "redis_pipeline"

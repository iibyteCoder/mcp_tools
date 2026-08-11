"""数据库连接测试配置 — 可通过环境变量覆盖."""

import os

MYSQL_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "192.168.1.34"),
    "port": int(os.getenv("MYSQL_PORT", "3316")),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", "lb7897127"),
    "database": os.getenv("MYSQL_DATABASE", "aica_test"),
}

NEO4J_CONFIG = {
    "uri": os.getenv("NEO4J_URI", "bolt://192.168.1.34:7688"),
    "user": os.getenv("NEO4J_USER", "neo4j"),
    "password": os.getenv("NEO4J_PASSWORD", "fskj123!@#"),
    "database": os.getenv("NEO4J_DATABASE", "neo4j"),
}

REDIS_CONFIG = {
    "host": os.getenv("REDIS_HOST", "localhost"),
    "port": int(os.getenv("REDIS_PORT", "6379")),
    "username": os.getenv("REDIS_USERNAME", ""),
    "password": os.getenv("REDIS_PASSWORD", ""),
    "db": int(os.getenv("REDIS_DB", "0")),
}

MINIO_CONFIG = {
    "endpoint": os.getenv("MINIO_ENDPOINT", "localhost:9002"),
    "access_key": os.getenv("MINIO_ACCESS_KEY", "admin"),
    "secret_key": os.getenv("MINIO_SECRET_KEY", "12345678"),
    "secure": os.getenv("MINIO_SECURE", "false").lower() == "true",
}

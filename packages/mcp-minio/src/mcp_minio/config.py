"""MinIO 连接配置."""

from typing import Any

from mcp_base.config import BaseConfig


class MinioConfig(BaseConfig):
    """MinIO 连接配置.

    所有设置均可通过 MINIO_ 前缀的环境变量覆盖
    (如 MINIO_ENDPOINT, MINIO_ACCESS_KEY).
    """

    endpoint: str = "localhost:9002"
    access_key: str = "admin"
    secret_key: str = ""
    secure: bool = False
    region: str = ""

    class Config:
        env_prefix = "MINIO_"

    def safe_info(self) -> dict[str, Any]:
        """返回遮蔽密钥的连接信息."""
        return {
            "endpoint": self.endpoint,
            "access_key": self.access_key,
            "secret_key": "****" if self.secret_key else "",
            "secure": self.secure,
            "region": self.region or "(auto)",
        }

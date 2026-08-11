# MCP MinIO Server

MinIO 对象存储操作 MCP 服务器。

## 安装

```bash
uv sync --all-packages
```

## 使用

```bash
uv run mcp-minio
```

## 配置

| 环境变量 | 默认值 | 说明 |
|--------|-------|------|
| `MINIO_ENDPOINT` | `localhost:9002` | MinIO 服务地址 |
| `MINIO_ACCESS_KEY` | `admin` | Access Key |
| `MINIO_SECRET_KEY` | (空) | Secret Key |
| `MINIO_SECURE` | `false` | 使用 TLS |

## 工具

- `minio_connect` / `disconnect` / `status` — 连接管理
- `minio_list_buckets` / `bucket_exists` / `make_bucket` / `remove_bucket` — Bucket 操作
- `minio_put_object` / `get_object` / `remove_object` / `list_objects` / `stat_object` / `copy_object` — 对象操作
- `minio_presigned_get_url` / `presigned_put_url` — 预签名 URL

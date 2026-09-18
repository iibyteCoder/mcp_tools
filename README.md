# MySQL CLI

基于 Python 3.10+ 和 uv 构建的 MySQL 客户端与 JSON 命令行工具。

## 项目结构

```text
./
├── libs/mysql-client/       # 类型化 MySQL 执行基础库
├── packages/mysql-cli/       # db-mysql 命令行工具
├── skills/mysql-cli/        # CLI 使用契约与连接参考
├── Claude.md                # 开发指南
└── pyproject.toml           # 工作区配置
```

## 可用工具

| 包名 | 描述 |
| ---- | ---- |
| [mysql-client](libs/mysql-client/pyproject.toml) | 类型化异步 MySQL 执行基础库 |
| [mysql-cli](packages/mysql-cli/pyproject.toml) | JSON-only `db-mysql` 命令行工具 |

## 快速开始

### 环境要求

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)

### 安装 CLI

```bash
# 在工作区同步依赖
uv sync

# 安装 db-mysql
uv tool install packages/mysql-cli
```

安装后可使用：

```bash
db-mysql --json profile list
```

### 开发模式

```bash
# 安装所有依赖
uv sync

# 运行 CLI 测试
uv run --project packages/mysql-cli pytest

# 运行客户端测试
uv run --project libs/mysql-client pytest
```

CLI 命令和参数约定请参考 [mysql-cli skill](skills/mysql-cli/SKILL.md)。

开发指南和最佳实践请参考 [Claude.md](Claude.md)。

## 许可证

MIT

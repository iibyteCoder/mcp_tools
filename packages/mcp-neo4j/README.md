# MCP Neo4j 服务器

基于 MCP 协议的 Neo4j 图数据库操作服务器，支持异步 Cypher 查询。

## 安装

### 全局安装

```bash
cd packages/mcp-neo4j
uv tool install .
```

安装后可直接运行：

```bash
mcp-neo4j
```

### 使用 uvx 运行（无需安装）

```bash
uvx --from /path/to/packages/mcp-neo4j mcp-neo4j
```

## 配置

支持环境变量或 `.env` 文件配置：

```bash
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password
NEO4J_DATABASE=neo4j
NEO4J_CONNECTION_TIMEOUT=30
NEO4J_MAX_CONNECTION_POOL_SIZE=50
```

## 可用工具

| 工具 | 说明 |
| ---- | ---- |
| `neo4j_connect` | 连接到 Neo4j 数据库，支持自定义连接参数 |
| `neo4j_disconnect` | 断开当前数据库连接 |
| `neo4j_query` | 执行 Cypher 只读查询（MATCH、RETURN） |
| `neo4j_execute` | 执行 Cypher 写入操作（CREATE、MERGE、DELETE、SET） |
| `neo4j_list_labels` | 列出数据库中所有节点标签 |
| `neo4j_list_relationship_types` | 列出数据库中所有关系类型 |
| `neo4j_list_properties` | 列出数据库中所有属性键 |
| `neo4j_describe_label` | 获取指定标签的节点属性结构 |

## 在 Claude Desktop 中使用

添加到 Claude Desktop 配置文件：

```json
{
  "mcpServers": {
    "neo4j": {
      "command": "mcp-neo4j",
      "env": {
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "your_password",
        "NEO4J_DATABASE": "neo4j"
      }
    }
  }
}
```

## 使用示例

### 查询节点

```text
查找所有名字以 "张" 开头的 Person 节点
```

### 创建节点和关系

```text
创建一个 Person 节点，姓名为 "张三"，年龄 30
创建一个 KNOWS 关系，从张三指向李四
```

### 探索图结构

```text
数据库中有哪些节点标签？
显示 Person 节点使用了哪些属性
```

### 复杂查询

```text
查找张三和李四之间的所有最短路径
统计每个人认识多少人
```

## 连接参数

| 参数 | 环境变量 | 默认值 |
| ---- | -------- | ------ |
| URI | `NEO4J_URI` | `bolt://localhost:7687` |
| 用户名 | `NEO4J_USER` | `neo4j` |
| 密码 | `NEO4J_PASSWORD` | `""` |
| 数据库 | `NEO4J_DATABASE` | `neo4j` |
| 连接超时 | `NEO4J_CONNECTION_TIMEOUT` | `30` |
| 最大连接池 | `NEO4J_MAX_CONNECTION_POOL_SIZE` | `50` |

## 技术特性

- 基于 `neo4j` 官方异步驱动实现
- 支持连接池管理
- 支持参数化 Cypher 查询，防止注入攻击
- 自动连接验证

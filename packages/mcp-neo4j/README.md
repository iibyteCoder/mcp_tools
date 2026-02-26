# MCP Neo4j

MCP server for Neo4j graph database operations.

## Installation

```bash
uv tool install .
```

## Configuration

Set environment variables with `NEO4J_` prefix:

```bash
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=your_password
export NEO4J_DATABASE=neo4j
```

## Available Tools

- `neo4j_connect` - Connect to Neo4j database
- `neo4j_disconnect` - Disconnect from database
- `neo4j_query` - Execute Cypher query (MATCH)
- `neo4j_execute` - Execute write query (CREATE, MERGE, DELETE, SET)
- `neo4j_list_labels` - List all node labels
- `neo4j_list_relationship_types` - List all relationship types
- `neo4j_list_properties` - List all property keys
- `neo4j_describe_label` - Get schema for a specific label

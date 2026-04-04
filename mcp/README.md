# IRIS MCP Server

`iris-mcp-server` is an independent Python package that exposes the IRIS read-only search API as Model Context Protocol tools.

## Scope

This package only talks to the existing HTTP search API under `/api/search/v1`. It does not import from the main `app` package, does not connect to Neo4j directly, and does not reuse the main application container.

## Tools

- `search_capabilities`
- `search_entities_query`
- `search_source_query`
- `search_query`

Each tool returns:

- short text content for human-readable summaries
- structured content for MCP clients that validate output schemas

## Installation

```bash
pip install -e .
```

For development:

```bash
pip install -e .[dev]
```

## Configuration

Core environment variables:

- `IRIS_SEARCH_API_BASE_URL` required. Accepts either the service root, such as `http://localhost:8000`, or the full search API prefix, such as `http://localhost:8000/api/search/v1`.
- `IRIS_SEARCH_API_KEY` optional.
- `IRIS_SEARCH_API_AUTH_SCHEME` optional. One of `x-api-key`, `bearer`, `none`. Default is `x-api-key` when an API key is set, otherwise `none`.
- `IRIS_MCP_ALLOW_CLIENT_EMBEDDING_FALLBACK` optional. Default `false`. When enabled, `search_query` may compute `query_vector` locally if the IRIS search API disallows built-in embedding.

HTTP client settings:

- `IRIS_SEARCH_API_TIMEOUT_SECONDS` default `30`
- `IRIS_SEARCH_API_RETRY_COUNT` default `2`
- `IRIS_SEARCH_API_DEFAULT_LIMIT` default `5`
- `IRIS_MCP_LOG_LEVEL` default `INFO`

Streamable HTTP settings:

- `IRIS_MCP_HOST` default `127.0.0.1`
- `IRIS_MCP_PORT` default `8000`
- `IRIS_MCP_STREAMABLE_HTTP_PATH` default `/mcp`
- `IRIS_MCP_JSON_RESPONSE` default `true`
- `IRIS_MCP_STATELESS_HTTP` default `true`

OpenAI embedding fallback settings:

- `IRIS_OPENAI_API_KEY` required when `IRIS_MCP_ALLOW_CLIENT_EMBEDDING_FALLBACK=true`
- `IRIS_OPENAI_BASE_URL` optional. Supports OpenAI-compatible embedding endpoints.
- `IRIS_OPENAI_EMBEDDING_MODEL` required when `IRIS_MCP_ALLOW_CLIENT_EMBEDDING_FALLBACK=true`
- `IRIS_OPENAI_EMBEDDING_DIMENSIONS` optional. If set, requests this output dimension from the embedding API.
- `IRIS_OPENAI_TIMEOUT_SECONDS` default `30`

## Running

### stdio

```bash
iris-mcp-server
```

### Streamable HTTP

```bash
iris-mcp-server-http
```

Or explicitly:

```bash
iris-mcp-server --transport streamable-http --port 8000
```

Clients connect to `http://localhost:8000/mcp` by default.

## Client-side Embedding Fallback

When all of the following are true, `search_query` can generate `query_vector` locally before calling IRIS:

- mode is `vector` or `hybrid`
- the caller did not provide `query_vector`
- `IRIS_MCP_ALLOW_CLIENT_EMBEDDING_FALLBACK=true`
- IRIS capabilities say the matched permission source does not allow built-in embedding
- `query_text` is present

This allows MCP clients to keep using semantic search even when the IRIS search API requires callers to supply vectors explicitly.

Example:

```bash
set IRIS_MCP_ALLOW_CLIENT_EMBEDDING_FALLBACK=true
set IRIS_OPENAI_API_KEY=sk-...
set IRIS_OPENAI_EMBEDDING_MODEL=text-embedding-3-small
iris-mcp-server-http
```

## MCP Client Examples

### Claude Code style HTTP registration

```bash
claude mcp add --transport http iris http://localhost:8000/mcp
```

### stdio JSON config shape

```json
{
  "command": "iris-mcp-server",
  "env": {
    "IRIS_SEARCH_API_BASE_URL": "http://localhost:8000",
    "IRIS_SEARCH_API_KEY": "your-secret"
  }
}
```

## Tool Notes

- `search_capabilities` calls `GET /api/search/v1/capabilities`
- `search_entities_query` calls `POST /api/search/v1/entities/query`
- `search_source_query` calls `POST /api/search/v1/sources/query`
- `search_query` calls `POST /api/search/v1/search`

Errors are translated into stable MCP tool results with `isError=true` and a structured `error` object containing the status code, message, and retry hint.

For `search_query`, successful structured results also include:

- `embedding_fallback_used`
- `embedding_model`

## Testing

```bash
pytest
ruff check .
```
"""CLI entrypoints for the IRIS MCP server."""

from __future__ import annotations

import argparse

from iris_mcp_server.client import IrisSearchApiClient
from iris_mcp_server.config import IrisMcpSettings, get_settings
from iris_mcp_server.embedding_client import OpenAIEmbeddingClient
from iris_mcp_server.logging_utils import configure_logging
from iris_mcp_server.server import create_server


def main(argv: list[str] | None = None) -> int:
    """Run the MCP server with stdio by default."""

    parser = _build_parser(default_transport="stdio")
    args = parser.parse_args(argv)
    settings = get_settings()
    return _run(args.transport, settings, args.host, args.port)


def main_http(argv: list[str] | None = None) -> int:
    """Run the MCP server with streamable HTTP by default."""

    parser = _build_parser(default_transport="streamable-http")
    args = parser.parse_args(argv)
    settings = get_settings()
    return _run(args.transport, settings, args.host, args.port)


def _build_parser(default_transport: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="iris-mcp-server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default=default_transport,
        help="MCP transport to run",
    )
    parser.add_argument("--host", default=None, help="HTTP host override")
    parser.add_argument("--port", type=int, default=None, help="HTTP port override")
    return parser


def _run(
    transport: str,
    settings: IrisMcpSettings,
    host: str | None,
    port: int | None,
) -> int:
    configure_logging(settings.iris_mcp_log_level)
    client = IrisSearchApiClient(settings)
    embedding_client = OpenAIEmbeddingClient(settings) if settings.client_embedding_enabled else None
    mcp = create_server(
        settings,
        client,
        embedding_client,
        host=host or settings.iris_mcp_host,
        port=port or settings.iris_mcp_port,
        streamable_http_path=settings.iris_mcp_streamable_http_path,
        json_response=settings.iris_mcp_json_response,
        stateless_http=settings.iris_mcp_stateless_http
    )

    if transport == "streamable-http":
        mcp.run(transport="streamable-http")
        return 0

    mcp.run(transport="stdio")
    return 0
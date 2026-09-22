"""Expose the mtg-mcp stdio server as authenticated streamable MCP HTTP."""

import asyncio
import os

from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from fastmcp.server import create_proxy
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier
from starlette.responses import PlainTextResponse


async def main() -> None:
    command = os.environ.get("MTG_COMMANDER_BINARY", "/usr/local/bin/mtg-mcp")
    transport = StdioTransport(command=command, args=[], cwd="/tmp")

    token = os.environ.get("MTG_MCP_BEARER", "").strip()
    auth = StaticTokenVerifier(tokens={
        token: {"client_id": "mtg", "scopes": ["mcp"]},
    }) if token else None

    async with Client(transport) as backend:
        bridge = create_proxy(
            backend,
            name="mtg-commander",
            auth=auth,
            instructions="Magic: The Gathering Commander research tools.",
        )

        @bridge.custom_route("/healthz", methods=["GET"])
        async def health(_request):
            try:
                await asyncio.wait_for(backend.ping(), timeout=3)
            except Exception:
                return PlainTextResponse("backend unavailable\n", status_code=503)
            return PlainTextResponse("ok\n")

        await bridge.run_async(
            transport="streamable-http",
            host=os.environ.get("MTG_HOST", "0.0.0.0"),
            port=int(os.environ.get("MTG_COMMANDER_PORT", "8001")),
            path="/mcp",
            stateless=False,
            show_banner=False,
        )


if __name__ == "__main__":
    asyncio.run(main())

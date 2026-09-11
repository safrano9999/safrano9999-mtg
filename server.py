"""Serve one persistent MTG stdio backend over authenticated MCP HTTP."""

import asyncio
import os
import sys
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from fastmcp.server import create_proxy
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier
from starlette.responses import PlainTextResponse


async def main(component):
    root = Path(__file__).resolve().parent
    if component == "commander":
        command = os.environ.get("MTG_COMMANDER_BINARY", "/usr/local/bin/mtg-mcp")
        args, default_port = [], 8000
    else:
        command = "/usr/bin/node"
        args, default_port = [str(root / "index.js")], 8001
    transport = StdioTransport(
        command=command, args=args, cwd="/tmp",
        env={key: os.environ[key] for key in (
            "ARCHIDEKT_USERNAME", "ARCHIDEKT_PASSWORD", "ARCHIDECKS",
        ) if key in os.environ},
    )
    token = os.environ.get("MTG_MCP_BEARER", "").strip()
    auth = StaticTokenVerifier(tokens={
        token: {"client_id": "mtg", "scopes": ["mcp"]},
    }) if token else None
    decks = os.environ.get("ARCHIDECKS", "").strip()
    instructions = f"Hinterlegte Archidekt-Decks: {decks}." if decks else None
    port = int(os.environ.get(f"MTG_{component.upper()}_PORT", default_port))
    if not 1 <= port <= 65535:
        raise ValueError("MCP port must be between 1 and 65535")

    # Both upstreams use initialize-based MCP. Keep their cache/login alive.
    async with Client(transport, mode="legacy") as backend:
        bridge = create_proxy(
            backend, name=f"mtg-{component}", auth=auth,
            instructions=instructions, provider_error_strategy="raise",
        )

        @bridge.custom_route("/healthz", methods=["GET"])
        async def health(_request):
            try:
                await asyncio.wait_for(backend.ping(), timeout=3)
            except Exception:
                return PlainTextResponse("backend unavailable\n", status_code=503)
            return PlainTextResponse("ok\n")

        await bridge.run_async(
            transport="http", host=os.environ.get("MTG_HOST", "0.0.0.0"),
            port=port, path="/mcp", stateless=False, show_banner=False,
        )


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {"commander", "archidekt"}:
        raise SystemExit("Usage: server.py commander|archidekt")
    asyncio.run(main(sys.argv[1]))

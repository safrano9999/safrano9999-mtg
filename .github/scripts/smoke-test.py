#!/usr/bin/env python3
# Source of truth: SCRIPTS/githubactions. Generated copies are overwritten.
"""Check service selection and MCP HTTP using only synthetic credentials."""
import asyncio
import os
import subprocess

import httpx
from fastmcp import Client


async def main():
    token = os.environ.get("MTG_MCP_BEARER", "")
    decks = os.environ.get("ARCHIDECKS", "").strip()
    expected_archidekt = {"create_deck", "list_decks", "read_deck", "update_deck", "lookup_cards", "search_cards"}
    for component, port, count in [("commander", 8000, 19), ("archidekt", 8001, 6)]:
        port = int(os.environ.get(f"MTG_{component.upper()}_PORT", port))
        url = f"http://127.0.0.1:{port}"
        enabled = os.environ.get(f"MTG_{component.upper()}_ENABLED", "true") != "false"
        state = subprocess.check_output([
            "systemctl", "show", f"mtg-{component}.service", "--property=ActiveState", "--value",
        ], text=True).strip()
        assert state == ("active" if enabled else "inactive"), (component, state)
        async with httpx.AsyncClient(timeout=5) as http:
            if not enabled:
                try:
                    await http.get(url + "/healthz")
                except httpx.ConnectError:
                    pass
                else:
                    raise AssertionError(f"Disabled {component} still accepts HTTP connections")
                print(f"{component}: service inactive and port closed OK", flush=True)
                continue
            health = await http.get(url + "/healthz")
            assert health.status_code == 200, (component, health.status_code)
            if token:
                for headers in [{}, {"Authorization": "Bearer invalid-test-token"}]:
                    response = await http.post(url + "/mcp", headers=headers, json={
                        "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                            "protocolVersion": "2025-11-25", "capabilities": {},
                            "clientInfo": {"name": "mtg-smoke", "version": "1"},
                        },
                    })
                    assert response.status_code == 401, (component, response.status_code)
        async with Client(url + "/mcp", auth=token or None, mode="legacy") as client:
            tools = await client.list_tools()
            names = {tool.name for tool in tools}
            assert len(tools) == count, (component, names)
            if component == "archidekt":
                assert names == expected_archidekt
            instructions = client.initialize_result.instructions
            assert instructions == (f"Hinterlegte Archidekt-Decks: {decks}." if decks else None), instructions
            assert await client.ping()
        print(f"{component}: health, bearer, initialize and {count} tools OK", flush=True)


asyncio.run(main())

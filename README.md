# safrano9999-mtg

This image is based on the pinned [`ghcr.io/dnviti/archidekt-mcp-server`](https://github.com/dnviti/archidekt-mcp-server) image at digest `sha256:40faa0f80522162eb1465bad112ba82e1c46dd04536f21419248bfcb49266f8d`, whose upstream Dockerfile uses `python:3.13-slim` rather than Alpine.
Our fork adds four reproducible Archidekt patches: [`authenticated.patch`](integrations/archidekt/patches/authenticated.patch), [`http_base.patch`](integrations/archidekt/patches/http_base.patch), [`public_collection.patch`](integrations/archidekt/patches/public_collection.patch), and [`account_identity.patch`](integrations/archidekt/patches/account_identity.patch).
Together, they fix deck update and deletion endpoints, `token`/`access_token` handling, private collection API normalization, and server-side account and token renewal.
Because Archidekt mixes JWT-only and Bearer-only routes, `http_base.py` selects the configured scheme from `ARCHIDEKT_MCP_AUTH_SCHEME`, enforces the known route-specific schemes, and can optionally retry with the other scheme.
`ARCHIDEKT_USERNAME` and `ARCHIDEKT_PASSWORD` are read only from the MCP `.env`; client credentials are ignored, and stale Redis login data is never used as the source for renewal.
The Nathan Commander MCP is built unchanged from [`nathanmartins/mtg-mcp`](https://github.com/nathanmartins/mtg-mcp) at the pinned revision; [PR #48](https://github.com/nathanmartins/mtg-mcp/pull/48) proposes native optional HTTP support, while this image currently wraps the pinned stdio binary with FastMCP on port `8001`.

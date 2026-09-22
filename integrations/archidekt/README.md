# Archidekt runtime corrections

This deployment uses [dnviti/archidekt-mcp-server](https://github.com/dnviti/archidekt-mcp-server)
alongside Nathan's Commander server. It replaces the Command Tower service
in the Fedora container for this configuration. Set `MTG_COMMANDER_ENABLED=true`
and `MTG_ARCHIDEKT_ENABLED=false` in the Fedora instance.

Use exactly these two MCP endpoints for the OpenClaw `mtg` agent:

| Server | Internal URL | OpenClaw selection |
| --- | --- | --- |
| mtg-commander | `http://safrano9999-mtg:8000/mcp` | `MCP_ALLOW=mtg` |
| archidekt-mcp | `http://archidekt-mcp:8000/mcp` | `MCP_ALLOW=mtg` |

Replace the existing Archidekt URL and bearer in the ucore ENV. Remove the
port-8001 endpoint from that configuration. Hermes retains global MCP access.
Each endpoint uses its own bearer; the external Archidekt server uses the
access token issued by its MCP OAuth flow.

## Corrections

`upstream.json` records the exact image digest, source revision and before/after
SHA-256 checksums. The patches reproduce the running fixes:

- Deck updates use `PATCH /api/decks/{id}/update/`.
- Deck deletion uses `DELETE /api/decks/{id}/` and handles an empty HTTP 204.
- Authenticated collection reads use `GET /api/collection/{id}/v2/` with the
  configured `Authorization` scheme and pagination. The deployment sets
  `ARCHIDEKT_MCP_AUTH_SCHEME=bearer`, matching the current Archidekt API.
  Private HTML collection pages return 404 even with an authorization header.
  The API's nested card data is normalized for the existing collection filters;
  anonymous public HTML reads stay supported.

The request helper accepts `bearer` or `jwt` and rejects unknown values. The
configured value is used for routes that accept either scheme; the known
personal-deck v3 route is normalized to `Bearer`, and the curated identity
route is normalized to `JWT`. The optional `ARCHIDEKT_MCP_AUTH_FALLBACK` flag
can retry one 401/403 with the other scheme, but remains disabled by default.

The server-side account wrapper reads `ARCHIDEKT_USERNAME` and
`ARCHIDEKT_PASSWORD` only from the MCP environment. Client-supplied account
credentials are ignored; an MCP-authenticated context or the configured
server account is used instead. Only patch differences are stored here.
Original modules are obtained from the pinned image. The third-party image
itself is unchanged.

## Prepare or restore the persistent patches

Run as the Podman user, after Smart1 has pulled the image from `upstream.json`:

```sh
python3 integrations/archidekt/prepare.py \
  "$HOME/.config/containers/archidekt-mcp-patches"
```

This needs Python 3, Git and Podman. It starts a temporary container with no
network, extracts the four original modules, verifies their checksums, applies
the patches and verifies the resulting checksums before writing any file.
It does not start the MCP, change account settings, or restart existing services.

The Quadlet binds the four patched files read-only over their matching Python
modules. The combined MTG image copies the same four verified runtime files
into the pinned Archidekt package during its build.
The files survive reboots and container recreation. After replacing patch
files in an existing deployment, restart `archidekt-mcp.service` to mount them.
When updating the image digest, regenerate and test the patches and checksums.

## Quadlet and authentication

`archidekt-mcp.container.example` and `archidekt-mcp.env.example` describe the
internal deployment. Adapt the Podman network name if needed. Install the
Quadlet as `~/.config/containers/systemd/archidekt-mcp.container` and the ENV as
`~/.config/containers/archidekt-mcp.env` with mode 0600. Preserve an existing ENV.
Then run `systemctl --user daemon-reload` and start `archidekt-mcp.service`.

The example depends on an existing `redis.service` on the same network. It
uses Redis DB 1 with the `archidekt-mcp` prefix. Paperless uses DB 0; its Redis
data volume and hostname alias can remain in place. No host port is published.
Keep Redis persistence enabled because it also holds MCP login/session state.

The localhost OAuth issuer matches the existing local bootstrap: authorize
inside the container and inject the issued bearer into ucore. A new remote
browser OAuth setup needs a reachable HTTPS issuer; see the
[upstream deployment documentation](https://github.com/dnviti/archidekt-mcp-server/blob/main/docs/deployment.md).
Credentials, OAuth tokens, Redis contents and generated instance files belong
outside Git. Patching an existing installation preserves its authentication.

## Verification and rollback

The GitHub compatibility workflow prepares the modules from the pinned image
and runs the collection regressions in that image without network access.
It checks empty and paginated collections, card fields, public HTML access,
authentication failures and malformed API responses. No account is required.

The deployed fixes were also checked with real deck create/update/delete
operations and authenticated collection reads. Temporary test decks were
removed; the collection correction made no deck or collection writes.

To roll back, remove the relevant module's `Volume=` line from the Quadlet,
run `systemctl --user daemon-reload`, and restart `archidekt-mcp.service`.

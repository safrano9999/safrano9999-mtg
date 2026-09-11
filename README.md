# safrano9999-mtg

Fedora 44 container with two independent systemd services and MCP HTTP endpoints:

| Service | Internal endpoint | Backend |
| --- | --- | --- |
| mtg-commander | `http://safrano9999-mtg:8000/mcp` | [nathanmartins/mtg-mcp](https://github.com/nathanmartins/mtg-mcp), 19 research tools |
| mtg-archidekt | `http://safrano9999-mtg:8001/mcp` | Command Tower fork, 6 deck and card tools |

Archidekt tools: `create_deck`, `list_decks`, `read_deck`, `update_deck`,
`lookup_cards`, `search_cards`. Custom-card tools are removed. The upstream
documentation and attribution are preserved in [UPSTREAM-README.md](UPSTREAM-README.md).

For the deployment with Nathan plus the external 16-tool Archidekt MCP, see
[Archidekt integration and persistent runtime patches](integrations/archidekt/README.md).
That configuration disables the bundled Command Tower service and uses the
digest-pinned third-party image with shared Redis and verified Quadlet patches.

## Setup

Run `./setup.sh --config-only safrano9999-mtg` to generate a named instance,
or use `--pull` / `--build`. Setup uses the common hardlinked Safrano `config.sh`,
instance helper, and Examples. It prints the ready-to-use Quadlet/systemd commands.
Runtime files are in `CONTAINER/safrano9999-mtg/`, including `safrano9999-mtg.env`.

The three source Examples are `env.mtg.example`, `config.mtg.conf_example`, and
`container.mtg.example`. Optional settings:

| ENV | Purpose |
| --- | --- |
| `MTG_MCP_BEARER` | Shared MCP bearer; blank disables authentication. Generate with `openssl rand -hex 32`. |
| `ARCHIDEKT_USERNAME` | Optional account username; deck/account tools need both login fields. |
| `ARCHIDEKT_PASSWORD` | Optional account password. |
| `ARCHIDECKS` | Optional CSV of reference deck IDs, included in MCP initialize instructions. No access restriction. |

Card search and Commander public reads work without account credentials.
Archidekt login is cached in memory and automatically renewed on use before expiry.
The container needs no persistent volume; decks remain at Archidekt.
Both services get injected values through systemd `PassEnvironment`.

### Select which services start

`MTG_COMMANDER_ENABLED` and `MTG_ARCHIDEKT_ENABLED` are optional `true`/`false`
settings in `config.mtg.conf_example`, both defaulting to `true`. Setup writes
them into the instance configuration, which Quadlet loads using `EnvironmentFile`.
The existing generator also omits published ports for disabled services.

You can override the selection directly in the Quadlet's `[Container]` section:

```ini
Environment=MTG_COMMANDER_ENABLED=true
Environment=MTG_ARCHIDEKT_ENABLED=false
```

This starts only Commander on port 8000. Reverse the values for Archidekt only;
set both to `true` for both services, or both to `false` to leave both stopped.
systemd evaluates the variables before starting each service. The container
healthcheck checks only enabled endpoints and succeeds when both are disabled.
Apply changes by restarting the container; after editing the Quadlet, run
`systemctl --user daemon-reload` first. To preserve changes across setup runs,
use the instance configuration or the existing `ADDITIONAL_LINE` fields.

Use `CONTAINER_NR=TUN` and `ADDITIONAL_LINE=Network=rafael` for Podman-network
access without host publishing. External ports are optional and independently
configurable through the existing publish-port fields. Each endpoint also has
an unauthenticated `/healthz` that checks its backend connection.

In OpenClaw configure each endpoint with its bearer, private-network access,
and `MCP_ALLOW=mtg`. Hermes ignores this OpenClaw agent selection.

## Build

The GitHub Actions workflow builds and tests the Fedora image, then publishes
`ghcr.io/safrano9999/safrano9999-mtg:latest` and a dated tag. Its source of truth
is `SCRIPTS/githubactions/safrano9999-mtg`; generated build files live in
`.github/scripts` and `.github/workflows`. Dependencies are installed at build
time, without a Python venv or startup downloads.

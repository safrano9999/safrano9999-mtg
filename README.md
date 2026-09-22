# safrano9999-mtg

Ein gemeinsames MCP-Image auf Basis des gepinnten
`ghcr.io/dnviti/archidekt-mcp-server`-Images. Es enthält genau zwei HTTP-MCP-Dienste:

- `archidekt-mcp` auf `http://safrano9999-mtg:8000/mcp`
- `mtg-commander` auf `http://safrano9999-mtg:8001/mcp`

Die drei korrigierten Archidekt-Module für Bearer-Authentifizierung, Deck-Updates
und private Collection-Abfragen werden beim Image-Build fest eingebaut. Der
Commander-Server wird aus dem gepinnten Nathan-Revision gebaut und als stdio-
Backend über FastMCP 3 veröffentlicht.

Die Dienste werden nicht auf Host-Ports veröffentlicht. Andere Container im
`rafael`-Netz erreichen sie direkt über `safrano9999-mtg:8000` bzw.
`safrano9999-mtg:8001`; Caddy braucht dafür keine Portfreigabe.

Die Redis- und OAuth-Daten bleiben außerhalb des Images. Der neue Container nutzt
dieselbe `rafael`-Podman-Network und dieselbe Redis-Datenbank/Key-Präfix wie der
bisherige Archidekt-Dienst; dadurch bleiben bestehende Credentials und Sessions
verfügbar.

## Image

Der Build läuft ausschließlich über die GitHub Action `container-image.yml`
und veröffentlicht `ghcr.io/safrano9999/safrano9999-mtg`. Lokale Builds sind
nicht vorgesehen.

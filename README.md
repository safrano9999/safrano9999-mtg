# safrano9999-mtg

Ein gemeinsames MCP-Image auf Basis des gepinnten
`ghcr.io/dnviti/archidekt-mcp-server`-Images. Es enthält genau zwei HTTP-MCP-Dienste:

- `archidekt-mcp` auf `http://safrano9999-mtg:8000/mcp`
- `mtg-commander` auf `http://safrano9999-mtg:8001/mcp`

Die vier korrigierten Archidekt-Module für Authentifizierung, Deck-Updates,
private Collection-Abfragen und serverseitige Account-Auflösung werden beim
Image-Build fest eingebaut. Der
Commander-Server wird aus dem gepinnten Nathan-Revision gebaut und als stdio-
Backend über FastMCP 3 veröffentlicht.

Die Dienste werden nicht auf Host-Ports veröffentlicht. Andere Container im
`rafael`-Netz erreichen sie direkt über `safrano9999-mtg:8000` bzw.
`safrano9999-mtg:8001`; Caddy braucht dafür keine Portfreigabe.

Die Redis- und OAuth-Daten bleiben außerhalb des Images. Der neue Container nutzt
dieselbe `rafael`-Podman-Network und dieselbe Redis-Datenbank/Key-Präfix wie der
bisherige Archidekt-Dienst; dadurch bleiben bestehende Credentials und Sessions
verfügbar.

## Was im Image gepatcht ist

Das Image enthält das unveränderte, per Digest gepinnte Upstream-Image plus vier
reproduzierbare Archidekt-Patches. Die Patchquellen liegen unter
`integrations/archidekt/patches/`, die daraus erzeugten Laufzeitdateien unter
`integrations/archidekt/runtime/`. `integrations/archidekt/upstream.json` hält
Upstream-Revision sowie Original- und Patch-SHA256 fest; `prepare.py` prüft diese
Kette vor dem Build. Das Containerfile kopiert die geprüften Dateien in die
Python-Installation des Images.

| Datei | Änderung |
| --- | --- |
| `account_identity.py` | Der Account kommt ausschließlich aus der serverseitigen `.env` bzw. aus dem MCP-Auth-Kontext. Benutzername und Passwort aus Client-Argumenten werden nie übernommen. Bei einer Token-Erneuerung werden alte Login-Daten aus Redis nicht mehr verwendet: Der Login läuft immer mit der `.env`, und das Zurückschreiben des neuen Tokens nach Redis ist nur noch Best-Effort. Ein veralteter oder nicht erreichbarer Redis-Eintrag kann dadurch keinen erfolgreichen Login mehr blockieren. |
| `authenticated.py` | Akzeptiert sowohl `token` als auch `access_token` aus der Archidekt-Loginantwort. Korrigiert außerdem die Deck-Endpunkte: Update über `PATCH /api/decks/{id}/update/`, Löschen über `DELETE /api/decks/{id}/`; eine leere `204`-Antwort beim Löschen wird korrekt behandelt. |
| `http_base.py` | Normalisiert die Authentifizierung serverseitig auf `bearer` oder `jwt` aus `ARCHIDEKT_MCP_AUTH_SCHEME`. `decks/v3` wird immer mit Bearer und `decks/curated` immer mit JWT aufgerufen. Optional kann mit `ARCHIDEKT_MCP_AUTH_FALLBACK=true` bei `401`/`403` einmalig das jeweils andere Schema versucht werden. Ein vom Client mitgegebenes Schema wird nicht blind übernommen. |
| `public_collection.py` | Private Collections werden über die authentifizierte JSON-API `/api/collection/{id}/v2/` gelesen statt über die private HTML-Ansicht. Verschachtelte Karten-, Printing-, Set-, Mana-Cost-, Foil-/Etched- und ID-Felder werden vereinheitlicht; öffentliche HTML-Collections bleiben möglich. |

### Auth- und Redis-Ablauf

1. Der Client darf Tools aufrufen, liefert aber niemals die serverseitigen
   Archidekt-Login-Daten.
2. Für einen neuen Login oder eine Erneuerung werden die Zugangsdaten aus der
   MCP-`.env` verwendet.
3. Das neue Token wird nach Redis geschrieben, sofern Redis erreichbar ist.
   Redis ist damit Session-/Cache-Speicher, aber nicht mehr die Quelle für
   Benutzername oder Passwort. Ein alter Redis-Login kann einen frischen,
   erfolgreichen Login nicht mehr durch einen `401` ersetzen.

Die MCP-Endpunkte und die Tool-Liste bleiben unverändert. Die Änderungen wirken
innerhalb des Images und betreffen nur Authentifizierung, Archidekt-API-Pfade,
Collection-Auflösung und die Redis-Erneuerung.

## Image

Der Build läuft ausschließlich über die GitHub Action `container-image.yml`
und veröffentlicht `ghcr.io/safrano9999/safrano9999-mtg`. Lokale Builds sind
nicht vorgesehen.

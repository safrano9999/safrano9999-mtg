"""Run the Archidekt MCP and native mtg-commander HTTP server together."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time


def main() -> int:
    env = os.environ.copy()
    children: list[subprocess.Popen[bytes]] = []

    archidekt = subprocess.Popen(
        [sys.executable, "-m", "archidekt_commander_mcp.server"],
        env=env,
    )
    children.append(archidekt)

    if env.get("MTG_COMMANDER_ENABLED", "true").strip().lower() != "false":
        commander = subprocess.Popen(
            [env.get("MTG_COMMANDER_BINARY", "/usr/local/bin/mtg-mcp")],
            env=env,
        )
        children.append(commander)

    def stop(_signum: int, _frame: object) -> None:
        for child in children:
            if child.poll() is None:
                child.terminate()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and any(c.poll() is None for c in children):
            time.sleep(0.1)
        for child in children:
            if child.poll() is None:
                child.kill()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    while True:
        for child in children:
            result = child.poll()
            if result is not None:
                for other in children:
                    if other is not child and other.poll() is None:
                        other.terminate()
                return result
        time.sleep(0.5)


if __name__ == "__main__":
    raise SystemExit(main())

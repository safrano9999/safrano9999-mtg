#!/usr/bin/env python3
# Source of truth: SCRIPTS/githubactions. Generated copies are overwritten.
"""Reproduce the deployed modules and run regression tests without credentials."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=["podman", "docker"], default="podman")
    args = parser.parse_args()
    integration = Path.cwd() / "integrations/archidekt"
    upstream = json.loads((integration / "upstream.json").read_text())
    with tempfile.TemporaryDirectory(prefix="archidekt-check-") as temporary:
        prepared = Path(temporary)
        subprocess.run(
            [sys.executable, str(integration / "prepare.py"), str(prepared), "--engine", args.engine],
            check=True,
        )
        test = (integration / "tests/collection-regression.py").read_text()
        payload = json.dumps({"source": (prepared / "public_collection.py").read_text()})
        subprocess.run(
            [args.engine, "run", "--rm", "--pull=never", "--network=none", "-i",
             "--entrypoint", "python", upstream["image"], "-c", test],
            input=payload, text=True, check=True,
        )


if __name__ == "__main__":
    main()

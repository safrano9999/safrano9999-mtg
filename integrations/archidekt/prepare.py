#!/usr/bin/env python3
"""Prepare the verified runtime modules from the pinned, locally pulled image."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


def prepare(output: Path, engine: str) -> None:
    root = Path(__file__).resolve().parent
    upstream = json.loads((root / "upstream.json").read_text())
    filenames = list(upstream["files"])
    default_module_directory = upstream["module_directory"]
    source_specs = {
        name: (
            specification.get("module_directory", default_module_directory),
            specification.get("source_name", name),
        )
        for name, specification in upstream["files"].items()
    }
    extract = (
        "import json;from pathlib import Path;"
        f"specs={source_specs!r};"
        "print(json.dumps({name:(Path(directory)/filename).read_text() "
        "for name,(directory,filename) in specs.items()}))"
    )
    sources = json.loads(subprocess.check_output(
        [engine, "run", "--rm", "--pull=never", "--network=none",
         "--entrypoint", "python", upstream["image"], "-c", extract], text=True,
    ))
    with tempfile.TemporaryDirectory(prefix="archidekt-patches-") as temporary:
        work = Path(temporary)
        for name, specification in upstream["files"].items():
            source = sources[name].encode()
            if hashlib.sha256(source).hexdigest() != specification["original_sha256"]:
                raise RuntimeError(f"Upstream module changed: {name}")
            (work / name).write_bytes(source)
            patch = root / "patches" / specification["patch"]
            subprocess.run(["git", "apply", "--check", str(patch)], cwd=work, check=True)
            subprocess.run(["git", "apply", str(patch)], cwd=work, check=True)
            patched = (work / name).read_bytes()
            if hashlib.sha256(patched).hexdigest() != specification["patched_sha256"]:
                raise RuntimeError(f"Patched module checksum differs: {name}")
            compile(patched, name, "exec")

        # Publish only after both modules have passed their checksum checks.
        output.mkdir(parents=True, exist_ok=True)
        for name in filenames:
            fd, temporary_name = tempfile.mkstemp(prefix=f".{name}-", dir=output)
            try:
                with os.fdopen(fd, "wb") as target:
                    target.write((work / name).read_bytes())
                    os.fchmod(target.fileno(), 0o644)
                os.replace(temporary_name, output / name)
            finally:
                if os.path.exists(temporary_name):
                    os.unlink(temporary_name)
    print(f"Prepared {len(filenames)} verified runtime modules in {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--engine", choices=["podman", "docker"], default="podman")
    args = parser.parse_args()
    prepare(args.output.expanduser().resolve(), args.engine)

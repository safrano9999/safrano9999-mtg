#!/usr/bin/env python3
"""Prepare one container instance from cached example release assets."""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path, PurePosixPath


NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
ASSIGNMENT_RE = re.compile(r"^[ \t]*(?:export[ \t]+)?([A-Za-z_][A-Za-z0-9_]*)=")
COMMENTED_VOLUME_RE = re.compile(
    r"^[ \t]*#[ \t]*(?:export[ \t]+)?([A-Za-z_][A-Za-z0-9_]*_VOLUMES)="
)
EXAMPLE_ARCHIVE_PATTERNS = (
    "env*example",
    "config*example",
    "container*example",
    "config*.container",
)


class SetupError(RuntimeError):
    """A safe, user-facing setup error."""


def log(message: str) -> None:
    print(message, file=sys.stderr)


def ask(prompt: str) -> str:
    print(prompt, end="", file=sys.stderr, flush=True)
    return sys.stdin.readline().strip()


def release_repository(specification: str) -> str:
    name = specification.split("@", 1)[0]
    if not NAME_RE.fullmatch(name):
        raise SetupError(f"Invalid repository name: {name}")
    return name


def github_release(repository: str) -> dict[str, object]:
    result = subprocess.run(
        [
            "gh",
            "api",
            f"repos/safrano9999/{repository}/releases/tags/latest",
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        detail = result.stderr.strip()
        suffix = f": {detail}" if detail else ""
        raise SetupError(f"Cannot read latest release for {repository}{suffix}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise SetupError(f"Invalid GitHub release response for {repository}") from error
    if not isinstance(payload, dict):
        raise SetupError(f"Invalid GitHub release response for {repository}")
    return payload


def asset_metadata(repository: str) -> tuple[int, int, float] | None:
    asset_name = f"{repository}-examplefiles.zip"
    release = github_release(repository)
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise SetupError(f"Latest release has no assets: {repository}")
    for asset in assets:
        if not isinstance(asset, dict) or asset.get("name") != asset_name:
            continue
        asset_id = asset.get("id")
        size = asset.get("size")
        updated_at = asset.get("updated_at")
        if not isinstance(asset_id, int) or not isinstance(size, int):
            break
        if not isinstance(updated_at, str):
            break
        try:
            timestamp = dt.datetime.fromisoformat(
                updated_at.replace("Z", "+00:00")
            ).timestamp()
        except ValueError as error:
            raise SetupError(
                f"Invalid asset timestamp for {repository}: {updated_at}"
            ) from error
        return asset_id, size, timestamp
    return None


def valid_zip(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            return archive.testzip() is None
    except (OSError, zipfile.BadZipFile):
        return False


def zip_has_examples(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            return any(
                not info.is_dir()
                and any(
                    fnmatch.fnmatchcase(PurePosixPath(info.filename).name, pattern)
                    for pattern in EXAMPLE_ARCHIVE_PATTERNS
                )
                for info in archive.infolist()
            )
    except (OSError, zipfile.BadZipFile):
        return False


def download_asset(
    repository: str,
    asset_id: int,
    size: int,
    timestamp: float,
    target: Path,
) -> None:
    temporary = target.with_name(f".{target.name}.download-{uuid.uuid4().hex}")
    try:
        with temporary.open("wb") as output:
            result = subprocess.run(
                [
                    "gh",
                    "api",
                    "-H",
                    "Accept: application/octet-stream",
                    f"repos/safrano9999/{repository}/releases/assets/{asset_id}",
                ],
                check=False,
                stdout=output,
                stderr=subprocess.PIPE,
            )
        if result.returncode != 0:
            detail = result.stderr.decode(errors="replace").strip()
            suffix = f": {detail}" if detail else ""
            raise SetupError(f"Cannot download {target.name}{suffix}")
        if temporary.stat().st_size != size:
            raise SetupError(f"Downloaded asset size mismatch: {target.name}")
        if not valid_zip(temporary):
            raise SetupError(f"Downloaded asset is not a valid ZIP: {target.name}")
        os.replace(temporary, target)
        os.utime(target, (timestamp, timestamp))
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def safe_member(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise SetupError(f"Unsafe ZIP member: {name}")
    return path


def extract_asset(archive_path: Path, target: Path) -> None:
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}.extract-", dir=target.parent))
    backup = target.with_name(f".{target.name}.backup-{uuid.uuid4().hex}")
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for info in archive.infolist():
                relative = safe_member(info.filename)
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise SetupError(f"ZIP symlink is not allowed: {info.filename}")
                destination = temporary.joinpath(*relative.parts)
                if info.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output)
                os.chmod(destination, mode & 0o777 or 0o644)
        if target.exists() or target.is_symlink():
            os.replace(target, backup)
        os.replace(temporary, target)
        if backup.exists():
            if backup.is_dir() and not backup.is_symlink():
                shutil.rmtree(backup)
            else:
                backup.unlink()
        timestamp = archive_path.stat().st_mtime
        os.utime(target, (timestamp, timestamp))
    except Exception:
        if backup.exists() and not target.exists():
            os.replace(backup, target)
        raise
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
        if backup.exists():
            if backup.is_dir() and not backup.is_symlink():
                shutil.rmtree(backup)
            else:
                backup.unlink()


def synchronize_asset(cache: Path, repository: str, offline: bool) -> Path | None:
    archive = cache / f"{repository}-examplefiles.zip"
    extracted = cache / repository
    changed = False
    if offline:
        if not archive.is_file() or not valid_zip(archive):
            raise SetupError(f"Offline example asset is missing: {archive}")
        log(f"  [{repository}] using offline example asset")
    else:
        try:
            metadata = asset_metadata(repository)
            if metadata is None:
                log(f"  [{repository}] no example asset; skipped")
                return None
            asset_id, size, timestamp = metadata
            current = (
                archive.is_file()
                and archive.stat().st_size == size
                and archive.stat().st_mtime >= timestamp
                and valid_zip(archive)
            )
            if not current:
                log(f"  [{repository}] downloading {archive.name}")
                download_asset(repository, asset_id, size, timestamp, archive)
                changed = True
            else:
                log(f"  [{repository}] example asset current")
        except (OSError, SetupError) as error:
            if not archive.is_file() or not valid_zip(archive):
                raise
            log(f"  [{repository}] GitHub unavailable; using cached asset ({error})")

    if not zip_has_examples(archive):
        log(f"  [{repository}] no configuration examples; skipped")
        return None

    if changed or not extracted.is_dir() or extracted.stat().st_mtime < archive.stat().st_mtime:
        extract_asset(archive, extracted)
        log(f"  [{repository}] examples extracted")
    return extracted


def matching_files(directory: Path, kind: str, output: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    patterns = {
        "env": ("env*example",),
        "config": ("config*example",),
        "container": ("container*example", "config*.container"),
    }[kind]
    result: list[Path] = []
    for pattern in patterns:
        for path in sorted(directory.glob(pattern)):
            if path == output or not path.is_file():
                continue
            result.append(path)
    return result


def merged_keyed(files: list[Path]) -> str:
    output: list[str] = []
    seen: set[str] = set()
    for path in files:
        pending: list[str] = []
        for raw in path.read_text(encoding="utf-8").splitlines():
            volume = COMMENTED_VOLUME_RE.match(raw)
            if volume:
                key = volume.group(1)
                if key not in seen:
                    seen.add(key)
                    output.extend(pending)
                    line = re.sub(r"^[ \t]*#[ \t]*", "", raw)
                    line = re.sub(r"^[ \t]*export[ \t]+", "", line)
                    output.extend((f"# {line}", ""))
                pending.clear()
                continue
            if not raw.strip() or raw.lstrip().startswith("#"):
                pending.append(raw)
                continue
            assignment = ASSIGNMENT_RE.match(raw)
            if assignment:
                key = assignment.group(1)
                if key not in seen:
                    seen.add(key)
                    output.extend(pending)
                    line = re.sub(r"^[ \t]*export[ \t]+", "", raw)
                    output.extend((line, ""))
                pending.clear()
                continue
            pending.clear()
    return "\n".join(output) + ("\n" if output else "")


def write_if_changed(path: Path, content: str) -> None:
    encoded = content.encode()
    if path.is_file() and not path.is_symlink() and path.read_bytes() == encoded:
        return
    temporary = path.with_name(f".{path.name}.merge-{uuid.uuid4().hex}")
    try:
        temporary.write_bytes(encoded)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def merge_examples(repo: Path, sources: list[Path]) -> None:
    for filename, kind in (
        ("env.example", "env"),
        ("config.conf_example", "config"),
        ("container.example", "container"),
    ):
        output = repo / filename
        files: list[Path] = []
        for source in sources:
            files.extend(matching_files(source, kind, output))
        write_if_changed(output, merged_keyed(files))
        log(f"  Merged {filename} ({len(files)} sources) -> {filename}")


def read_nr(path: Path) -> str:
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()
            if line.startswith("CONTAINER_NR="):
                return line.split("=", 1)[1].strip()
    return ""


def mode(path: Path) -> str | int | None:
    value = read_nr(path)
    if value.lower() in {"", "blank", "manual"}:
        return None
    if value.upper() == "TUN":
        return "TUN"
    if value.isdigit() and 2 <= int(value) <= 5:
        return int(value)
    raise SetupError(f"Invalid CONTAINER_NR={value!r} in {path}")


def write_nr(path: Path, value: str | int | None) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    replacement = f"CONTAINER_NR={value or ''}"
    output: list[str] = []
    for line in lines:
        if line.split("=", 1)[0].strip() == "CONTAINER_NR":
            if replacement:
                output.append(replacement)
                replacement = ""
        else:
            output.append(line)
    if replacement:
        if output and output[-1]:
            output.append("")
        output.append(replacement)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(output) + "\n", encoding="utf-8")


def label(value: str | int | None) -> str:
    if isinstance(value, int):
        return f"Portrange {value * 10000} - {(value + 1) * 10000 - 1}"
    return value or "manual"


def choose_instance(instances: Path, requested: str, default_name: str) -> tuple[str, bool]:
    names = sorted(path.name for path in instances.iterdir() if path.is_dir() and not path.is_symlink())
    if requested:
        name = requested
        is_new = name not in names
    elif not sys.stdin.isatty():
        if names:
            name, is_new = names[0], False
        elif default_name:
            name, is_new = default_name, True
        else:
            raise SetupError("No container exists; pass INSTANCE")
    elif not names:
        prompt = "  New container name"
        if default_name:
            prompt += f" [{default_name}]"
        name = ask(f"{prompt}: ") or default_name
        is_new = True
    else:
        new_index = len(names) + 1
        log("\n  Container:")
        for index, candidate in enumerate(names, 1):
            log(f"    ({index}) {candidate}")
        log(f"    ({new_index}) new\n")
        choice = ask(f"  Choose [1-{new_index}] (default: 1): ") or "1"
        if choice == str(new_index):
            prompt = "  New container name"
            if default_name and default_name not in names:
                prompt += f" [{default_name}]"
            name = ask(f"{prompt}: ") or (default_name if default_name not in names else "")
            if name in names:
                raise SetupError(f"Container already exists: {name}")
            is_new = True
        elif choice.isdigit() and 1 <= int(choice) <= len(names):
            name, is_new = names[int(choice) - 1], False
        else:
            raise SetupError(f"Invalid container choice: {choice}")
    if not NAME_RE.fullmatch(name):
        raise SetupError(f"Invalid container name: {name}")
    return name, is_new


def choose_port_mode(instances: Path, name: str, is_new: bool) -> None:
    config = instances / name / f"{name}_container.conf"
    if not is_new:
        mode(config)
        return
    modes = {
        path.name: mode(path / f"{path.name}_container.conf")
        for path in instances.iterdir()
        if path.is_dir() and not path.is_symlink() and path.name != name
    }
    highest = max((value for value in modes.values() if isinstance(value, int)), default=1)
    next_nr = highest + 1 if highest < 5 else None
    current: str | int | None = "TUN"
    if sys.stdin.isatty():
        used = {
            selected: candidate
            for candidate, selected in modes.items()
            if isinstance(selected, int)
        }
        options: list[str | int | None] = ["TUN"]
        if next_nr is not None:
            options.append(next_nr)
        options.extend(number for number in range(2, 6) if number != next_nr)
        options.append(None)
        log("\n  Publish ports:")
        for index, option in enumerate(options, 1):
            suffix = " (default)" if option == "TUN" else ""
            if option == next_nr:
                suffix = " (next: +1)"
            elif option in used:
                suffix = f" (used: {used[option]})"
            log(f"    ({index}) {label(option)}{suffix}")
        choice = ask(f"\n  Choose [1-{len(options)}] (default: 1): ") or "1"
        if not choice.isdigit() or not 1 <= int(choice) <= len(options):
            raise SetupError(f"Invalid publish-port choice: {choice}")
        current = options[int(choice) - 1]
        if current in used:
            raise SetupError(f"CONTAINER_NR={current} is already used by {used[current]}")
    config.parent.mkdir(parents=True, exist_ok=True)
    write_nr(config, current)


def hardlink(source: Path, target: Path) -> None:
    try:
        if not target.is_symlink() and os.path.samefile(source, target):
            return
    except FileNotFoundError:
        pass
    if target.exists() and target.is_dir():
        raise SetupError(f"Hardlink target is a directory: {target}")
    temporary = target.with_name(f".{target.name}.link-{uuid.uuid4().hex}")
    try:
        os.link(source, temporary)
        os.replace(temporary, target)
    except OSError as error:
        raise SetupError(f"Cannot hardlink {source} -> {target}: {error}") from error
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def symlink(source: Path, target: Path, replace_file: bool = False) -> None:
    relative = os.path.relpath(source, target.parent)
    if target.is_symlink() and os.readlink(target) == relative:
        return
    if target.exists() and not target.is_symlink():
        if target.is_dir() or not replace_file:
            raise SetupError(f"Refusing to replace instance file: {target}")
    temporary = target.with_name(f".{target.name}.link-{uuid.uuid4().hex}")
    try:
        temporary.symlink_to(relative)
        os.replace(temporary, target)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def link_instance(repo: Path, cache: Path, config: Path, instance: Path) -> None:
    instance.mkdir(parents=True, exist_ok=True)
    for source in sorted(repo.iterdir()):
        if "example" not in source.name or not source.is_file():
            continue
        symlink(source, instance / source.name, replace_file=True)
    for source in (
        config,
        config.parent / "sqlite_persistence.sh",
        config.parent / "optional_persistence.sh",
    ):
        if source.is_file():
            hardlink(source, instance / source.name)
    symlink(cache, instance / "safrano9999")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", type=Path)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--name", default="")
    parser.add_argument("--default-name", default="")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--repository", action="append", default=[])
    parser.add_argument("--example-dir", type=Path, action="append", default=[])
    return parser.parse_args()


def main() -> None:
    args = parse_arguments()
    repo = args.repo.resolve()
    if not repo.is_dir():
        raise SetupError(f"Repository directory not found: {repo}")
    config = args.config if args.config.is_absolute() else repo / args.config
    config = config.resolve()
    if not config.is_file():
        raise SetupError(f"config.sh not found: {config}")
    if args.default_name and not NAME_RE.fullmatch(args.default_name):
        raise SetupError(f"Invalid default container name: {args.default_name}")

    cache = repo / "safrano9999-examples"
    instances = repo / "CONTAINER"
    cache.mkdir(parents=True, exist_ok=True)
    instances.mkdir(parents=True, exist_ok=True)

    repositories: list[str] = []
    seen: set[str] = set()
    for specification in args.repository:
        repository = release_repository(specification)
        if repository.casefold() in seen:
            continue
        seen.add(repository.casefold())
        repositories.append(repository)

    extracted = []
    for repository in repositories:
        directory = synchronize_asset(cache, repository, args.offline)
        if directory is not None:
            extracted.append(directory)
    example_dirs = [repo]
    for directory in args.example_dir:
        resolved = directory if directory.is_absolute() else repo / directory
        example_dirs.append(resolved.resolve())
    example_dirs.extend(extracted)
    merge_examples(repo, example_dirs)

    for instance in sorted(path for path in instances.iterdir() if path.is_dir() and not path.is_symlink()):
        link_instance(repo, cache, config, instance)

    name, is_new = choose_instance(instances, args.name, args.default_name)
    instance = instances / name
    instance.mkdir(parents=True, exist_ok=True)
    choose_port_mode(instances, name, is_new)
    link_instance(repo, cache, config, instance)
    print(instance)


if __name__ == "__main__":
    try:
        main()
    except (OSError, SetupError, subprocess.SubprocessError) as error:
        print(f"container-instance-setup: {error}", file=sys.stderr)
        raise SystemExit(1)

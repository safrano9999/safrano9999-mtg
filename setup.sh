#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="ghcr.io/safrano9999/safrano9999-mtg:latest"
INSTANCE="${CONFIG_CONTAINER_NAME:-}"
OPERATION=""
for argument in "$@"; do
    case "$argument" in
        --config-only) OPERATION=config ;;
        --pull) OPERATION=pull ;;
        --build) OPERATION=build ;;
        --help|-h)
            echo 'Usage: ./setup.sh [--config-only|--pull|--build] [INSTANCE]'
            exit 0 ;;
        --*) echo "Unknown option: $argument" >&2; exit 2 ;;
        *) [ -z "$INSTANCE" ] || { echo 'Select only one instance' >&2; exit 2; }
           INSTANCE="$argument" ;;
    esac
done

# Use the common hardlinked helpers; instance files and repeat groups are
# generated entirely by the existing Safrano configuration pipeline.
arguments=("$ROOT" --config "$ROOT/config.sh" --default-name safrano9999-mtg)
[ -z "$INSTANCE" ] || arguments+=(--name "$INSTANCE")
INSTANCE_DIR="$(python3 "$ROOT/container-instance-setup.py" "${arguments[@]}")"
INSTANCE="${INSTANCE_DIR##*/}"
(
    cd "$INSTANCE_DIR"
    CONFIG_CONTAINER_NAME="$INSTANCE" CONFIG_CONTAINER_IMAGE="$IMAGE" bash ./config.sh
)
chmod 0600 "$INSTANCE_DIR/$INSTANCE.env"

if [ -z "$OPERATION" ]; then
    echo 'Image: (1) pull GHCR (2) build locally (3) configuration only'
    read -rp 'Choose [1/2/3] (default: 1): ' choice
    case "${choice:-1}" in
        1) OPERATION=pull ;;
        2) OPERATION=build ;;
        3) OPERATION=config ;;
        *) echo 'Invalid image choice' >&2; exit 2 ;;
    esac
fi
case "$OPERATION" in
    pull) podman pull --retry 10 --retry-delay 5s "$IMAGE" ;;
    build) podman build --pull=always --file "$ROOT/.github/scripts/Containerfile" --tag "$IMAGE" "$ROOT" ;;
esac

python3 "$ROOT/quadlet_finish.py" \
    "$INSTANCE_DIR/$INSTANCE-compose.yml" "$INSTANCE_DIR/$INSTANCE.container" "$INSTANCE"

#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
./scripts/build_codec.sh
exec python3 -m comms.supervisor "$@"

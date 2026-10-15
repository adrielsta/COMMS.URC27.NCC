#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
./scripts/build_codec.sh
(cd vendor/anatomy && sha256sum -c SHA256SUMS)
python3 scripts/fetch_imagery.py --verify
python3 -m unittest discover -s tests -v "$@"
node --test tests/test_geoview.cjs

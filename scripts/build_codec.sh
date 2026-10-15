#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
build_dir="$repo_root/.build"
mkdir -p "$build_dir"

# Verify vendored codec provenance before compiling. No network or dependencies
# beyond the existing C++ toolchain are needed.
(cd "$repo_root/vendor/rovecomm" && sha256sum --check SHA256SUMS)
temporary_library="$(mktemp "$build_dir/librovecodec.XXXXXX.so")"
trap 'rm -f -- "$temporary_library"' EXIT
"${CXX:-g++}" -std=c++20 -O2 -shared -fPIC -Wall -Wextra \
    -I "$repo_root/vendor/rovecomm" \
    "$repo_root/native/rovecodec.cpp" \
    "$repo_root/vendor/rovecomm/RoveCommPacket.cpp" \
    -o "$temporary_library"
mv -f -- "$temporary_library" "$build_dir/librovecodec.so"
printf 'Built %s\n' "$build_dir/librovecodec.so"

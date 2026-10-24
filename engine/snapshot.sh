#!/bin/sh
# Snapshot the current engine binary as engine/versions/bp-<shortsha>[-dirty] for A/B testing with tools/arena.py.
#   engine/snapshot.sh [--build] [name]
# --build rebuilds first (engine/build.sh). Optional name overrides the suffix (bp-<name>).
set -e
cd "$(dirname "$0")"
if [ "$1" = "--build" ]; then ./build.sh; shift; fi
[ -x bp ] || { echo "engine/bp not built (run engine/build.sh)" >&2; exit 1; }
if [ -n "$1" ]; then
  tag="$1"
else
  tag="$(git rev-parse --short HEAD)"
  # Mark snapshots built from uncommitted engine sources.
  if ! git diff --quiet HEAD -- . 2>/dev/null || [ -n "$(git ls-files --others --exclude-standard -- . | grep -v '^versions/')" ]; then
    tag="$tag-dirty-$(date +%H%M%S)"
  fi
fi
mkdir -p versions
cp bp "versions/bp-$tag"
echo "engine/versions/bp-$tag"

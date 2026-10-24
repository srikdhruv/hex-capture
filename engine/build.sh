#!/bin/sh
# Portable build by default. BP_NATIVE=1 engine/build.sh adds -march=native for local speed.
set -e
cd "$(dirname "$0")"
FLAGS="-O3 -std=c++17 -pthread -Wall -Wno-misleading-indentation"
if [ "${BP_NATIVE:-0}" = "1" ]; then FLAGS="$FLAGS -march=native"; fi
${CXX:-g++} $FLAGS -o bp bp.cpp

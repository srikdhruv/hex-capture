#!/bin/sh
set -e
cd "$(dirname "$0")"
g++ -O3 -march=native -std=c++17 -pthread -Wall -Wno-misleading-indentation -o bp bp.cpp

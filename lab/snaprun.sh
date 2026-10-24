#!/bin/bash
# Snapshot lab code so later edits don't affect a running tournament. Usage: snaprun.sh <tag> <script> args...
tag=$1; shift
d=/tmp/claude-1000/-home-srikd-hex-capture/362302db-4859-47e1-8b23-315eef87deba/scratchpad/snap_$tag
rm -rf $d; mkdir -p $d/lab $d/reference
cp /home/srikd/hex-capture/reference/rules.mjs $d/reference/
cp /home/srikd/hex-capture/lab/*.mjs $d/lab/; cp -r /home/srikd/hex-capture/lab/cfg $d/lab/
cd $d/lab && node "$@"

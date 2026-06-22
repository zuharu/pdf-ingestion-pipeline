#!/bin/bash
# ABBYY FineReader v16 Bridge — Quick WSL wrapper
# Usage: ./abbyy.sh <input.pdf> [output-dir]
set -e
INPUT="${1:-input.pdf}"
OUTDIR="${2:-./output}"
mkdir -p "$OUTDIR"
ABBYY_PATH="/mnt/c/Zuharu/ABBYY FineReader PDF 16.0.14.7295/Installed/finereaderocr.exe"
"$ABBYY_PATH" "$(realpath "$INPUT")" /lang English /out "$(realpath "$OUTDIR")"
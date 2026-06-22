#!/bin/bash
# run_pipeline.sh — Runs on the vast.ai GPU instance
# Sequential VRAM pipeline: marker-pdf → Ollama VLM → Netlistify

set -euo pipefail

INPUT_DIR="/workspace/input"
OUTPUT_DIR="/workspace/output"
BOOK_DIR="$OUTPUT_DIR/brophy"
LOG_FILE="$OUTPUT_DIR/pipeline.log"

mkdir -p "$INPUT_DIR" "$OUTPUT_DIR" "$BOOK_DIR"

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

PDF_PATH=$(ls "$INPUT_DIR"/*.pdf 2>/dev/null | head -1)
if [ -z "$PDF_PATH" ]; then
    log "❌ No PDF found in $INPUT_DIR"
    exit 1
fi
PDF_NAME=$(basename "$PDF_PATH")
log "📄 Processing: $PDF_NAME ($(du -h "$PDF_PATH" | cut -f1))"

step_a() {
    log "══════════════════════════════════════════════"
    log "STEP A: marker-pdf GPU extraction"
    log "══════════════════════════════════════════════"
    log "[A] Installing marker-pdf..."
    pip install marker-pdf -q 2>&1 | tee -a "$LOG_FILE"
    log "[A] Extracting PDF to markdown + images..."
    marker_single "$PDF_PATH" "$BOOK_DIR/" --force_ocr 2>&1 | tee -a "$LOG_FILE"
    IMG_COUNT=$(find "$BOOK_DIR" -maxdepth 1 \( -iname "*.jpg" -o -iname "*.jpeg" -o -iname "*.png" \) | wc -l)
    log "[A] ✅ Done — $IMG_COUNT images extracted"
}

step_b() {
    log "══════════════════════════════════════════════"
    log "STEP B: VLM figure description via Ollama"
    log "══════════════════════════════════════════════"
    VLM_MODEL="${VLM_MODEL:-gemma4}"
    log "[B] Installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh 2>&1 | tee -a "$LOG_FILE"
    log "[B] Starting Ollama server..."
    ollama serve &
    sleep 3
    log "[B] Pulling $VLM_MODEL (first run downloads ~20GB)..."
    ollama pull "$VLM_MODEL" 2>&1 | tee -a "$LOG_FILE"
    log "[B] Describing figures..."
    python3 /workspace/vlm_local.py \
        --images-dir "$BOOK_DIR/" \
        --output "$BOOK_DIR/_enhanced.md" \
        --model "$VLM_MODEL" 2>&1 | tee -a "$LOG_FILE"
    log "[B] ✅ Done"
}

step_c() {
    log "══════════════════════════════════════════════"
    log "STEP C: Netlistify schematic → SPICE"
    log "══════════════════════════════════════════════"
    NETLISTIFY_DIR="/workspace/Netlistify"
    WEIGHT_URL="https://drive.google.com/uc?export=download&id=1Jlx9HNfrTIXrjIOyIL3zyy_rDrcfKKzZ"
    log "[C] Cloning Netlistify..."
    git clone https://github.com/NYCU-AI-EDA/Netlistify.git "$NETLISTIFY_DIR" 2>&1 | tee -a "$LOG_FILE"
    log "[C] Installing dependencies..."
    cd "$NETLISTIFY_DIR"
    pip install -r requirements.txt -q 2>&1 | tee -a "$LOG_FILE"
    pip install gdown ultralytics transformers -q 2>&1 | tee -a "$LOG_FILE"
    log "[C] Downloading pretrained weights..."
    mkdir -p "$NETLISTIFY_DIR/weights"
    gdown "$WEIGHT_URL" -O "$NETLISTIFY_DIR/weights/pretrained.pt" 2>&1 | tee -a "$LOG_FILE"
    log "[C] Running Netlistify inference..."
    mkdir -p "$BOOK_DIR/netlists/"
    python3 "$NETLISTIFY_DIR/inference.py" \
        --input "$BOOK_DIR/" \
        --output "$BOOK_DIR/netlists/" \
        --weights "$NETLISTIFY_DIR/weights/pretrained.pt" 2>&1 | tee -a "$LOG_FILE"
    NETLIST_COUNT=$(find "$BOOK_DIR/netlists/" -name "*.sp" 2>/dev/null | wc -l)
    log "[C] ✅ Done — $NETLIST_COUNT SPICE netlists"
}

cd /workspace
log "Starting pipeline..."
START_TOTAL=$(date +%s)
step_a
step_b
step_c
END_TOTAL=$(date +%s)
TOTAL_SEC=$((END_TOTAL - START_TOTAL))
log "✅ Pipeline complete in $((TOTAL_SEC / 60))m $((TOTAL_SEC % 60))s"
echo "DONE_MARKER" >> "$LOG_FILE"
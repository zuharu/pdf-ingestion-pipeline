#!/bin/bash
# run_pipeline.sh — Runs on the vast.ai GPU instance
# Sequential VRAM pipeline: marker-pdf → Ollama VLM → Netlistify
# VRAM freed between steps for optimal model loading

set -euo pipefail

INPUT_DIR="/workspace/input"
OUTPUT_DIR="/workspace/output"
BOOK_DIR="$OUTPUT_DIR/brophy"
LOG_FILE="$OUTPUT_DIR/pipeline.log"
PIPELINE_DIR="/workspace/pipeline"

mkdir -p "$INPUT_DIR" "$OUTPUT_DIR" "$BOOK_DIR"

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

PDF_PATH=$(ls "$INPUT_DIR"/*.pdf 2>/dev/null | head -1)
if [ -z "$PDF_PATH" ]; then
    log "❌ No PDF found"
    exit 1
fi
PDF_NAME=$(basename "$PDF_PATH")
log "📄 Processing: $PDF_NAME"

# ── Step A: marker-pdf GPU (VRAM ~5-8GB) ──
step_a() {
    log "STEP A: marker-pdf GPU extraction"
    
    # Fix: pin transformers<5.0.0 for surya compatibility
    log "[A] Installing marker-pdf..."
    pip install marker-pdf -q 2>&1 | tee -a "$LOG_FILE"
    pip install "transformers>=4.45.2,<5.0.0" "regex<2025.0.0,>=2024.4.28" -q 2>&1 | tee -a "$LOG_FILE"
    
    log "[A] Extracting PDF (this takes ~15 min for 484 pages)..."
    # NOTE: Use --output_dir, not positional arg!
    marker_single "$PDF_PATH" --output_dir "$BOOK_DIR/" --force_ocr 2>&1 | tee -a "$LOG_FILE"
    
    IMG_COUNT=$(find "$BOOK_DIR" -type f \( -iname "*.jpg" -o -iname "*.jpeg" -o -iname "*.png" \) 2>/dev/null | wc -l)
    log "[A] ✅ $IMG_COUNT images extracted, VRAM freed"
}

# ── Step B: VLM figure description via Ollama (VRAM ~20GB) ──
step_b() {
    log "STEP B: VLM figure description via Ollama"
    VLM_MODEL="${VLM_MODEL:-gemma4}"
    
    log "[B] Installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh 2>&1 | tee -a "$LOG_FILE"
    log "[B] Starting Ollama server..."
    ollama serve &
    sleep 3
    
    log "[B] Pulling $VLM_MODEL (first run downloads ~20GB)..."
    ollama pull "$VLM_MODEL" 2>&1 | tee -a "$LOG_FILE"
    
    log "[B] Describing figures via $VLM_MODEL..."
    python3 "$PIPELINE_DIR/cloud_pipeline/vlm_local.py" \
        --images-dir "$BOOK_DIR/" \
        --output "$BOOK_DIR/_enhanced.md" \
        --model "$VLM_MODEL" 2>&1 | tee -a "$LOG_FILE"
    log "[B] ✅ All figures described"
}

# ── Step C: Netlistify schematic → SPICE (VRAM ~6-8GB) ──
step_c() {
    log "STEP C: Netlistify schematic → SPICE"
    NETLISTIFY_DIR="/workspace/Netlistify"
    
    log "[C] Cloning Netlistify..."
    git clone https://github.com/NYCU-AI-EDA/Netlistify.git "$NETLISTIFY_DIR" 2>&1 | tee -a "$LOG_FILE"
    cd "$NETLISTIFY_DIR"
    pip install -r requirements.txt -q 2>&1 | tee -a "$LOG_FILE"
    pip install gdown ultralytics transformers -q 2>&1 | tee -a "$LOG_FILE"
    
    log "[C] Downloading pretrained weights..."
    mkdir -p "$NETLISTIFY_DIR/weights"
    gdown "https://drive.google.com/uc?export=download&id=1Jlx9HNfrTIXrjIOyIL3zyy_rDrcfKKzZ" \
        -O "$NETLISTIFY_DIR/weights/pretrained.pt" 2>&1 | tee -a "$LOG_FILE"
    
    log "[C] Running Netlistify inference..."
    mkdir -p "$BOOK_DIR/netlists/"
    python3 "$NETLISTIFY_DIR/inference.py" \
        --input "$BOOK_DIR/" \
        --output "$BOOK_DIR/netlists/" 2>&1 | tee -a "$LOG_FILE"
    
    NETLIST_COUNT=$(find "$BOOK_DIR/netlists/" -name "*.sp" 2>/dev/null | wc -l)
    log "[C] ✅ $NETLIST_COUNT SPICE netlists generated"
}

# ── Main ──
cd /workspace
log "Starting pipeline..."
START=$(date +%s)
step_a
step_b
step_c
END=$(date +%s)
DURATION=$((END - START))
log "✅ Pipeline complete in $((DURATION / 60))m $((DURATION % 60))s"
echo "DONE_MARKER" >> "$LOG_FILE"

#!/usr/bin/env python3
"""ABBY + OpenDataLoader Pipeline for Brophy test."""
import subprocess, sys, json, shutil, time, tempfile
from pathlib import Path
from datetime import datetime

ABBYY_EXE = Path("/mnt/c/Zuharu/ABBYY FineReader PDF 16.0.14.7295/Installed/finereaderocr.exe")
CHUNK_SIZE = 50
PDF_PATH = Path("/mnt/n/workspace_QNAP/user_files/PDF_Books/output_opendataloader/Basic_electronics_for_scientists_Brophy/Basic_electronics_for_scientists_Brophy.pdf")

WORK_DIR = Path("/mnt/n/workspace_QNAP/user_files/PDF_Books/output_opendataloader/Basic_electronics_for_scientists_Brophy")
CHUNKS_DIR = WORK_DIR / "abbyy_chunks"

def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def split_pdf():
    log("Checking qpdf...")
    subprocess.run(["qpdf", "--version"], capture_output=True, check=True)
    result = subprocess.run(["qpdf", "--show-npages", str(PDF_PATH)], capture_output=True, text=True, check=True)
    total_pages = int(result.stdout.strip())
    log(f"PDF: {total_pages} pages")
    tmp_dir = Path(tempfile.mkdtemp(prefix="abbyy_split_"))
    log(f"Splitting in: {tmp_dir}")
    tmp_pdf = tmp_dir / PDF_PATH.name
    shutil.copy2(PDF_PATH, tmp_pdf)
    chunks = []
    for start in range(1, total_pages + 1, CHUNK_SIZE):
        end = min(start + CHUNK_SIZE - 1, total_pages)
        chunk_name = f"chunk_{start:03d}_{end:03d}.pdf"
        tmp_path = tmp_dir / chunk_name
        subprocess.run(["qpdf", "--pages", str(tmp_pdf), f"{start}-{end}", "--", str(tmp_path)], capture_output=True, check=True)
        final_path = CHUNKS_DIR / chunk_name
        CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(tmp_path, final_path)
        chunks.append(final_path)
        log(f"  Created: {chunk_name}")
    shutil.rmtree(tmp_dir, ignore_errors=True)
    log(f"✅ {len(chunks)} chunks created")
    return chunks

def main():
    print(f"{'='*70}\n  ABBY + OpenDataLoader Pipeline — Brophy Test\n{'='*70}")
    log(f"Work dir: {WORK_DIR}")
    chunks = split_pdf()
    log(f"Split into {len(chunks)} chunks")

if __name__ == "__main__":
    main()

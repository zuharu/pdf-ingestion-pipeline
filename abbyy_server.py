#!/usr/bin/env python3
"""ABBYY FineReader FastAPI server for WSL."""
from fastapi import FastAPI
from pydantic import BaseModel
import subprocess, json
from pathlib import Path

app = FastAPI(title="ABBYY Bridge")
ABBYY_EXE = Path("/mnt/c/Zuharu/ABBYY FineReader PDF 16.0.14.7295/Installed/finereaderocr.exe")

class ExtractRequest(BaseModel):
    pdf_path: str
    output_dir: str
    lang: str = "English"

@app.post("/extract")
async def extract(req: ExtractRequest):
    result = subprocess.run([str(ABBYY_EXE), req.pdf_path, "/lang", req.lang, "/out", req.output_dir],
                          capture_output=True, text=True, timeout=900)
    return {"status": "ok" if result.returncode == 0 else "error", "stdout": result.stdout, "stderr": result.stderr}

@app.get("/health")
async def health():
    exists = ABBYY_EXE.exists()
    return {"status": "ok" if exists else "config_error", "abbyy_path": str(ABBYY_EXE), "exists": exists}

@app.get("/metadata")
async def metadata(pdf_path: str):
    import os
    p = Path(pdf_path)
    if not p.exists():
        return {"error": "File not found"}
    return {"filename": p.name, "size_mb": round(p.stat().st_size / 1e6, 1), "exists": True}

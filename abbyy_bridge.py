#!/usr/bin/env python3
"""ABBYY FineReader CLI bridge for PDF extraction."""
import subprocess, sys, json, shutil
from pathlib import Path
# Configuration
ABBYY_EXE = Path("/mnt/c/Zuharu/ABBYY FineReader PDF 16.0.14.7295/Installed/finereaderocr.exe")
def extract(pdf_path: Path, output_dir: Path, lang: str = "English"):
    output_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([str(ABBYY_EXE), str(pdf_path), "/lang", lang, "/out", str(output_dir)],
                          capture_output=True, text=True, timeout=900)
    return {"status": "ok" if result.returncode == 0 else "error", "output": output_dir}
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["extract"])
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("./output"))
    args = parser.parse_args()
    result = extract(args.input, args.output_dir)
    print(json.dumps(result, default=str))

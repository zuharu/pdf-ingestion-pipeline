#!/usr/bin/env python3
"""
vlm_local.py — Describe figures via self-hosted Ollama VLM.
Usage:
    python3 vlm_local.py --images-dir /path/to/figures --output _enhanced.md
"""

import os, sys, json, time, base64, argparse, requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("VLM_MODEL", "gemma4")
MAX_WORKERS = int(os.environ.get("VLM_WORKERS", "2"))
REQUEST_TIMEOUT = 120

PROMPTS = {
    "circuit": "You are an expert electronics engineer. Identify ALL components with values, signal flow, and function. Output SPICE netlist if possible.",
    "graph": "Describe the axes, curve shapes, key values, and what this graph demonstrates.",
    "photo": "Describe what equipment, components, or setup is visible.",
    "default": "Describe this figure in detail: elements, labels, and its purpose in an electronics textbook.",
}

def figure_type_from_name(filename: str) -> str:
    name = filename.lower()
    if any(k in name for k in ("schemati", "circuit", "fig_", "figure_")):
        return "circuit"
    if any(k in name for k in ("graph", "curve", "plot", "waveform")):
        return "graph"
    if any(k in name for k in ("photo", "picture")):
        return "photo"
    return "default"

def encode_image(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

def describe_image(image_path: str, model: str = DEFAULT_MODEL) -> dict:
    filename = Path(image_path).name
    fig_type = figure_type_from_name(filename)
    prompt = PROMPTS.get(fig_type, PROMPTS["default"])
    try:
        b64_image = encode_image(image_path)
        t0 = time.time()
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={"model": model, "messages": [{"role": "user", "content": prompt, "images": [b64_image]}],
                  "stream": False, "options": {"temperature": 0.1, "num_predict": 512}},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        elapsed = time.time() - t0
        data = resp.json()
        return {"filename": filename, "description": data.get("message", {}).get("content", ""),
                "tokens": data.get("eval_count", 0), "time_sec": round(elapsed, 2), "status": "ok"}
    except Exception as e:
        return {"filename": filename, "description": f"[ERROR: {e}]", "status": "error"}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--images-dir", required=True)
    parser.add_argument("--output", default="_enhanced.md")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--sample", type=int, default=0)
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    args = parser.parse_args()

    images_dir = Path(args.images_dir)
    if not images_dir.is_dir():
        print(f"❌ Images dir not found: {images_dir}")
        sys.exit(1)

    images = sorted(images_dir.glob("*.[jJ][pP][gG]"))
    images += sorted(images_dir.glob("*.[jJ][pP][eE][gG]"))
    images += sorted(images_dir.glob("*.[pP][nN][gG]"))

    if not images:
        print(f"❌ No images found")
        sys.exit(1)

    if args.sample > 0 and args.sample < len(images):
        import random; random.seed(42)
        images = random.sample(images, args.sample)

    print(f"📸 {len(images)} figures, model: {args.model}")

    results = {}
    total_tokens = 0
    errors = 0
    t_start = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        fut_map = {pool.submit(describe_image, str(img), args.model): img for img in images}
        for i, fut in enumerate(as_completed(fut_map), 1):
            img = fut_map[fut]
            try:
                result = fut.result()
                results[img.name] = result
                if result.get("status") == "ok":
                    total_tokens += result.get("tokens", 0)
                    print(f"  ✅ [{i}/{len(images)}] {img.name} ({result['time_sec']:.1f}s)")
                else:
                    errors += 1
                    print(f"  ❌ [{i}/{len(images)}] {img.name} — {result.get('status')}")
            except Exception as e:
                errors += 1
                results[img.name] = {"description": f"[FATAL: {e}]"}
                print(f"  💥 [{i}/{len(images)}] {img.name}")

    output_path = Path(args.output)
    with open(output_path, "w") as f:
        f.write(f"# Enhanced Markdown — VLM-described\n\n")
        f.write(f"**Model:** {args.model}  \n**Figures:** {len(images)} ({errors} errors)  \n\n---\n\n")
        for name, result in sorted(results.items()):
            f.write(f"### {name}\n\n{result.get('description', '')}\n\n---\n\n")

    print(f"\n✅ Done: {(time.time()-t_start)/60:.1f} min, {total_tokens} tokens, {errors} errors")
    print(f"   Output: {output_path.resolve()}")

if __name__ == "__main__":
    main()

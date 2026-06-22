#!/usr/bin/env python3
"""
orchestrate.py — Orchestrate PDF ingestion on a vast.ai GPU instance.

Rents a GPU (RTX 4090), clones the pipeline repo onto the instance,
executes run_pipeline.sh, downloads results, cleans up.

Usage:
    python3 orchestrate.py                              # Process Brophy.pdf
    python3 orchestrate.py --pdf my_book.pdf             # Specific PDF
    python3 orchestrate.py --gpu "RTX PRO 4000"         # Custom GPU
    python3 orchestrate.py --max-price 0.30              # Budget cap
    python3 orchestrate.py --dry-run                     # Show what would happen
"""

import os
import sys
import json
import time
import shutil
import subprocess
import argparse
from pathlib import Path
from datetime import datetime

# ── Paths ──
BASE_DIR = Path("/workspace_qnap/PDF_Ingestion_Pipeline")
PDF_INPUT = BASE_DIR / "pdf_input"
RESULT_DIR = BASE_DIR / "result"
FINISHED_DIR = BASE_DIR / "finished_pdf"

# ── Repo (public — no auth needed for clone) ──
REPO_URL = "https://github.com/zuharu/pdf-ingestion-pipeline.git"

# ── Config ──
DEFAULT_GPU = "RTX 4090"
DEFAULT_MAX_PRICE = 0.40
DOCKER_IMAGE = "pytorch/pytorch:2.4.0-cuda12.4-cudnn9-runtime"
DISK_GB = 50
SSH_KEY = Path.home() / ".ssh" / "id_ed25519"
POLL_INTERVAL = 15
MAX_WAIT_MIN = 10


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def run_cmd(cmd: str, capture: bool = False, timeout: int = 300) -> str:
    """Run a shell command and return output."""
    log(f"  $ {cmd[:120]}..." if len(cmd) > 120 else f"  $ {cmd}")
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=capture, text=True,
            timeout=timeout
        )
        if capture:
            return result.stdout.strip()
        return result.stdout or ""
    except subprocess.TimeoutExpired:
        log(f"  ⏱️  Command timed out after {timeout}s")
        return ""


def load_api_key() -> str:
    env_path = Path("/workspace_qnap/vast_ai/.env")
    if not env_path.exists():
        log("❌ API key not found")
        sys.exit(1)
    with open(env_path) as f:
        for line in f:
            if "VAST_API_KEY" in line and "=" in line:
                return line.split("=", 1)[1].strip()
    log("❌ VAST_API_KEY not found")
    sys.exit(1)


def search_gpu(gpu_name: str = DEFAULT_GPU, max_price: float = DEFAULT_MAX_PRICE) -> dict:
    log(f"🔍 Searching for {gpu_name} ≤ ${max_price}/hr...")
    cmd = (
        f'vastai search offers '
        f'"gpu_name={gpu_name} num_gpus=1 rentable=true" '
        f'-o dph_total+ --raw --limit 10'
    )
    output = run_cmd(cmd, capture=True, timeout=60)
    offers = json.loads(output) if output else []
    cheap = [o for o in offers if float(o.get("dph_total", 99)) <= max_price]
    if not cheap:
        log(f"❌ No {gpu_name} found under ${max_price}/hr")
        sys.exit(1)
    best = cheap[0]
    log(f"  ✅ Offer ID={best['id']} @ ${float(best['dph_total']):.4f}/hr")
    return best


def create_instance(offer_id: int) -> str:
    log(f"🚀 Creating instance...")
    cmd = (
        f'vastai create instance {offer_id} '
        f'--image "{DOCKER_IMAGE}" --disk {DISK_GB} --ssh --direct --raw'
    )
    output = run_cmd(cmd, capture=True, timeout=120)
    data = json.loads(output) if output else {}
    instance_id = data.get("new_contract", "")
    if not instance_id:
        log(f"❌ Failed: {data}")
        sys.exit(1)
    log(f"  ✅ Instance ID: {instance_id}")
    return str(instance_id)


def wait_for_running(instance_id: str) -> dict:
    log(f"⏳ Waiting for instance...")
    start = time.time()
    while time.time() - start < MAX_WAIT_MIN * 60:
        cmd = f'vastai show instance {instance_id} --raw'
        output = run_cmd(cmd, capture=True, timeout=30)
        if not output:
            time.sleep(POLL_INTERVAL); continue
        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            time.sleep(POLL_INTERVAL); continue
        status = data.get("actual_status", "unknown")
        log(f"     Status: {status} ({int(time.time()-start)}s)")
        if status == "running":
            ip = data.get("actual_ip") or data.get("public_ip", "")
            port = data.get("direct_port") or 22
            return {"host": ip, "port": port}
        elif status in ("exited", "offline", "unknown"):
            destroy_instance(instance_id)
            sys.exit(1)
        time.sleep(POLL_INTERVAL)
    log(f"⏱️  Timeout")
    destroy_instance(instance_id)
    sys.exit(1)


def upload_to_instance(ssh_info: dict, local_path: Path, remote_path: str = None):
    if not local_path.exists():
        return
    if remote_path is None:
        remote_path = f"/workspace/{local_path.name}"
    cmd = (
        f'scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null '
        f'-i {SSH_KEY} -P {ssh_info["port"]} '
        f'{"-r" if local_path.is_dir() else ""} '
        f'{local_path} root@{ssh_info["host"]}:{remote_path}'
    )
    run_cmd(cmd, timeout=120)
    log(f"  📤 Uploaded: {local_path.name}")


def exec_on_instance(ssh_info: dict, command: str, timeout: int = 3600) -> str:
    cmd = (
        f'ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null '
        f'-i {SSH_KEY} -p {ssh_info["port"]} '
        f'root@{ssh_info["host"]} '
        f'"cd /workspace && {command}"'
    )
    log(f"  ⚙️  Executing...")
    result = run_cmd(cmd, capture=True, timeout=timeout)
    lines = result.split("\n")
    log(f"     ({len(lines)} lines output)")
    for l in lines[-15:]:
        if l.strip():
            log(f"     {l}")
    return result


def download_from_instance(ssh_info: dict, remote_path: str, local_path: Path):
    local_path.mkdir(parents=True, exist_ok=True)
    port = ssh_info["port"]
    host = ssh_info["host"]
    cmd = (
        f'scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null '
        f'-i {SSH_KEY} -P {port} '
        f'-r root@{host}:{remote_path}/* {local_path}/'
    )
    run_cmd(cmd, timeout=300)
    files = list(local_path.rglob("*"))
    size = sum(f.stat().st_size for f in files if f.is_file())
    log(f"  📥 Downloaded: {len(files)} files ({size/1e6:.1f} MB)")


def destroy_instance(instance_id: str):
    if not instance_id:
        return
    log(f"💥 Destroying instance...")
    run_cmd(f'vastai destroy instance {instance_id} --raw', timeout=60)
    log("  ✅ Done")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", default="Brophy.pdf")
    parser.add_argument("--gpu", default=DEFAULT_GPU)
    parser.add_argument("--max-price", type=float, default=DEFAULT_MAX_PRICE)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-download", action="store_true")
    args = parser.parse_args()

    pdf_path = PDF_INPUT / args.pdf
    if not pdf_path.exists():
        log(f"❌ PDF not found: {pdf_path}")
        sys.exit(1)

    log(f"PDF: {pdf_path.name} ({pdf_path.stat().st_size/1e6:.0f} MB)")
    log(f"GPU: {args.gpu} ≤ ${args.max_price}/hr")

    if args.dry_run:
        log("🏁 Dry run — exiting")
        return

    try:
        input(f"\n🚀 Est. ~${(args.max_price/60)*25:.2f}. Press Enter...")
    except KeyboardInterrupt:
        sys.exit(0)

    instance_id = ""
    try:
        load_api_key()
        offer = search_gpu(args.gpu, args.max_price)
        instance_id = create_instance(offer["id"])
        ssh_info = wait_for_running(instance_id)

        log("📤 Uploading PDF...")
        upload_to_instance(ssh_info, pdf_path, "/workspace/input/")

        log("📦 Cloning pipeline repo...")
        exec_on_instance(ssh_info, f"git clone {REPO_URL} /workspace/pipeline")

        log("⚙️  Running pipeline...")
        exec_on_instance(ssh_info,
            "chmod +x /workspace/pipeline/cloud_pipeline/run_pipeline.sh && "
            "bash /workspace/pipeline/cloud_pipeline/run_pipeline.sh")

        if not args.skip_download:
            log("📥 Downloading...")
            download_from_instance(ssh_info, "/workspace/output", RESULT_DIR / pdf_path.stem)

        log("📦 Moving PDF to finished_pdf/...")
        FINISHED_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pdf_path, FINISHED_DIR / pdf_path.name)
        pdf_path.unlink()

        log(f"✅ Complete. Results: {RESULT_DIR / pdf_path.stem}")

    finally:
        if instance_id:
            destroy_instance(instance_id)


if __name__ == "__main__":
    main()

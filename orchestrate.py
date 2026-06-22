#!/usr/bin/env python3
"""
orchestrate.py — Orchestrate PDF ingestion on a vast.ai GPU instance.

Rents a GPU, clones pipeline repo onto instance, executes run_pipeline.sh,
downloads results, moves PDF to finished_pdf, destroys instance.

Usage:
    python3 orchestrate.py                              # Process Brophy.pdf
    python3 orchestrate.py --pdf my_book.pdf             # Specific PDF
    python3 orchestrate.py --gpu "RTX 5090"             # GPU model
    python3 orchestrate.py --max-price 0.25              # Budget cap
    python3 orchestrate.py --dry-run                     # Preview only
"""

import os, sys, json, time, shutil, subprocess, argparse
from pathlib import Path
from datetime import datetime

BASE_DIR = Path("/workspace_qnap/PDF_Ingestion_Pipeline")
PDF_INPUT = BASE_DIR / "pdf_input"
RESULT_DIR = BASE_DIR / "result"
FINISHED_DIR = BASE_DIR / "finished_pdf"

REPO_URL = "https://github.com/zuharu/pdf-ingestion-pipeline.git"
DEFAULT_GPU = "RTX 4090"
DEFAULT_MAX_PRICE = 0.40
DOCKER_IMAGE = "pytorch/pytorch:2.4.0-cuda12.4-cudnn9-runtime"
DISK_GB = 60
SSH_KEY = Path.home() / ".ssh" / "id_ed25519"
POLL_INTERVAL = 15
MAX_WAIT_MIN = 12


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def run_cmd(cmd, capture=False, timeout=300):
    log(f"  $ {cmd[:120]}..." if len(cmd) > 120 else f"  $ {cmd}")
    try:
        r = subprocess.run(cmd, shell=True, capture_output=capture, text=True, timeout=timeout)
        return r.stdout.strip() if capture else (r.stdout or "")
    except subprocess.TimeoutExpired:
        log(f"  ⏱️  Timeout after {timeout}s")
        return ""

def load_api_key():
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

def search_gpu(gpu_name=DEFAULT_GPU, max_price=DEFAULT_MAX_PRICE):
    """Search GPU with fallback chain: unverified → verified → any 24GB+. """
    log(f"🔍 Searching for {gpu_name} ≤ ${max_price}/hr...")
    
    # Try: exact GPU, unverified first (more offers, cheaper)
    for verified in [None, True]:
        ver_str = "verified=true " if verified else ""
        cmd = f'vastai search offers "gpu_name={gpu_name} num_gpus=1 rentable=true {ver_str}direct_port_count>=1" -o dph_total+ --raw --limit 10'
        output = run_cmd(cmd, capture=True, timeout=60)
        offers = json.loads(output) if output else []
        cheap = [o for o in offers if float(o.get("dph_total", 99)) <= max_price]
        if cheap:
            best = cheap[0]
            v = "✅" if best.get("verified") else "❌"
            log(f"  ✅ Offer ID={best['id']} @ ${float(best['dph_total']):.4f}/hr (reliab={best.get('reliability','N/A')}, ver={v})")
            return best
        log(f"    0 offers with verified={verified}, trying next...")
    
    # Fallback: any GPU with 24GB+ VRAM
    log(f"  ⚠️ {gpu_name} unavailable. Searching ANY 24GB+ GPU...")
    cmd = f'vastai search offers "gpu_ram>=24000 num_gpus=1 rentable=true direct_port_count>=1" -o dph_total+ --raw --limit 5'
    output = run_cmd(cmd, capture=True, timeout=60)
    offers = json.loads(output) if output else []
    cheap = [o for o in offers if float(o.get("dph_total", 99)) <= max_price]
    if cheap:
        fallback = cheap[0]
        log(f"  ✅ Fallback: {fallback.get('gpu_name','?')} ID={fallback['id']} @ ${float(fallback['dph_total']):.4f}/hr")
        return fallback
    
    log(f"❌ No GPU found under ${max_price}/hr")
    sys.exit(1)

def create_instance(offer_id):
    log(f"🚀 Creating instance...")
    cmd = f'vastai create instance {offer_id} --image "{DOCKER_IMAGE}" --disk {DISK_GB} --ssh --direct --raw'
    output = run_cmd(cmd, capture=True, timeout=120)
    data = json.loads(output) if output else {}
    iid = data.get("new_contract", "")
    if not iid:
        log(f"❌ Failed: {data.get('msg','unknown error')}")
        sys.exit(1)
    log(f"  ✅ Instance ID: {iid}")
    return str(iid)

def wait_for_running(instance_id):
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
            log(f"❌ Instance {status}")
            destroy_instance(instance_id)
            sys.exit(1)
        time.sleep(POLL_INTERVAL)
    log(f"⏱️  Timeout")
    destroy_instance(instance_id)
    sys.exit(1)

def scp_upload(ssh, local, remote=None):
    if not local.exists():
        return
    if remote is None:
        remote = f"/workspace/{local.name}"
    cmd = f'scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i {SSH_KEY} -P {ssh["port"]} {"-r" if local.is_dir() else ""} {local} root@{ssh["host"]}:{remote}'
    run_cmd(cmd, timeout=120)
    log(f"  📤 {local.name}")

def ssh_exec(ssh, command, timeout=3600):
    cmd = f'ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i {SSH_KEY} -p {ssh["port"]} root@{ssh["host"]} "cd /workspace && {command}"'
    log(f"  ⚙️  Executing...")
    result = run_cmd(cmd, capture=True, timeout=timeout)
    lines = result.split("\n")
    for l in lines[-15:]:
        if l.strip():
            log(f"     {l}")
    return result

def scp_download(ssh, remote, local):
    local.mkdir(parents=True, exist_ok=True)
    cmd = f'scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i {SSH_KEY} -P {ssh["port"]} -r root@{ssh["host"]}:{remote}/* {local}/'
    run_cmd(cmd, timeout=300)
    files = list(local.rglob("*"))
    size = sum(f.stat().st_size for f in files if f.is_file())
    log(f"  📥 {len(files)} files ({size/1e6:.1f} MB)")

def destroy_instance(iid):
    if not iid:
        return
    log(f"💥 Destroying {iid}...")
    run_cmd(f'vastai destroy instance {iid} --raw', timeout=60)
    log("  ✅ Destroyed")

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
        log(f"❌ PDF not found: {pdf_path}"); sys.exit(1)

    log(f"PDF: {pdf_path.name} ({pdf_path.stat().st_size/1e6:.0f} MB)")
    log(f"GPU: {args.gpu} ≤ ${args.max_price}/hr | IMG: {DOCKER_IMAGE}")

    if args.dry_run:
        log("🏁 Dry run — exiting"); return

    try:
        input(f"\n🚀 Est. ~${(args.max_price/60)*30:.2f}. Press Enter...")
    except KeyboardInterrupt:
        sys.exit(0)

    instance_id = ""
    try:
        load_api_key()
        offer = search_gpu(args.gpu, args.max_price)
        gpu_name = offer.get("gpu_name", "?")
        log(f"  Renting: {gpu_name}")
        
        instance_id = create_instance(offer["id"])
        ssh = wait_for_running(instance_id)
        
        log("📤 Uploading PDF...")
        scp_upload(ssh, pdf_path, "/workspace/input/")
        
        log("📦 Cloning pipeline repo...")
        ssh_exec(ssh, f"git clone {REPO_URL} /workspace/pipeline")
        
        log("⚙️  Running pipeline (30-40 min)...")
        ssh_exec(ssh, "bash /workspace/pipeline/cloud_pipeline/run_pipeline.sh")
        
        if not args.skip_download:
            log("📥 Downloading results...")
            scp_download(ssh, "/workspace/output", RESULT_DIR / pdf_path.stem)
        
        log("📦 Moving PDF to finished_pdf/...")
        FINISHED_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pdf_path, FINISHED_DIR / pdf_path.name)
        pdf_path.unlink()
        
        log(f"\n✅ COMPLETE — {gpu_name}")
        log(f"   Results: {RESULT_DIR / pdf_path.stem}")
        log(f"   PDF:     {FINISHED_DIR / pdf_path.name}")
    finally:
        if instance_id:
            destroy_instance(instance_id)

if __name__ == "__main__":
    main()

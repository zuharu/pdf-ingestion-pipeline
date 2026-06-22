# Unified Cloud GPU Pipeline — Implementation Plan

## Arsitektur

```mermaid
flowchart TD
    subgraph LOCAL[WSL /workspace_qnap/PDF_Ingestion_Pipeline]
        A[pdf_input/Brophy.pdf]
        G[orchestrate.py]
        H[result/]
        I[finished_pdf/]
    end
    subgraph GPU[Vast.ai Instance — RTX 4090]
        B[run_pipeline.sh]
        C[marker-pdf GPU]
        D[Ollama + Gemma 4]
        E[Netlistify GPU]
        F[output/]
    end
    A -- SCP upload --> B
    G -- SSH exec --> B
    B --> C --> D --> E --> F
    F -- SCP download --> H
    A -- SCP move --> I
    G -- vastai destroy --> GPU
```

## File yang Perlu Dibuat

| File | Fungsi |
|------|--------|
| `cloud_pipeline/run_pipeline.sh` | Entry script di GPU instance |
| `cloud_pipeline/vlm_local.py` | VLM via Ollama |
| `orchestrate.py` | Orchestrator lokal |

## Biaya

| Step | Time | Cost ($0.27/hr) |
|------|------|----------------|
| marker-pdf | 1 min | $0.005 |
| VLM describe | 20 min | $0.09 |
| Netlistify | 10 min | $0.05 |
| **Total** | **~31 min** | **~$0.15** |

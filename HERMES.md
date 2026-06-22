# ABBYY + OpenDataLoader Pipeline — PDF Ingestion

**Status:** 🚧 Phase 1 — Figure Description MVP
**Goal:** End-to-end academic PDF → structured markdown + figure descriptions

## Architecture

```
PDF → ABBYY/marker-pdf → Markdown + Images
                            │
                    ┌───────┴────────┐
                    │                │
            Figure Pipeline    Text Processing
           (VLM via OpenRouter)  (TBD)
                    │                │
                    └───────┬────────┘
                            │
                    Enhanced Markdown → Vault
```

## Scripts

| File | Purpose |
|------|---------|
| `figure_pipeline.py` | Main pipeline: classify → describe → embed |
| `llm_figure_test.py` | Test harness |
| `abbyy_server.py` | FastAPI for ABBYY on WSL |
| `abbyy_bridge.py` | CLI bridge to ABBYY |
| `abbyy.sh` | Quick WSL wrapper |
| `vlm_prompt_gen.py` | DeepSeek prompt generation |
| `vlm_describe.py` | VLM figure description |
| `orchestrate.py` | Cloud GPU orchestrator |
| `cloud_pipeline/` | GPU instance scripts |

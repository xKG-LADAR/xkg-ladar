# xKG-LADAR

**LLM-Assisted Automated Bug Diagnosis and Repair Leveraging Execution Knowledge Graphs**

A pipeline that transforms execution traces into structured knowledge graphs (xKGs) to drive LLM-based diagnosis and patch generation for bugs in Python projects from the [BugsInPy](https://github.com/soarsmu/BugsInPy) benchmark.

## Overview

The pipeline runs four steps per bug:
1. **Trace** (`run_trace.py`) - Instruments the failing test with PySnooper to capture an execution trace
2. **Condense** (`trace_condense.py`) - Filters and compresses the raw trace
3. **Knowledge Graph** (`build_trace_kg.py`) - Builds a KG of variable/control-flow relationships from the condensed trace
4. **Diagnose & Fix** (`debug_agent.py`) - Feeds the KG into Claude (Anthropic API) to diagnose the root cause and generate a patch

Results on 86 fully-traced bugs are in the `results/` directory.

## Prerequisites

- Python 3.12
- [BugsInPy](https://github.com/soarsmu/BugsInPy) cloned at `../BugsInPy` relative to this directory (i.e. `BugsInPy/` should be a sibling of this folder)
- BugsInPy framework binary on your PATH:
  ```bash
  export PATH=$PATH:/path/to/BugsInPy/framework/bin
  ```

## Setup

### 1. Clone BugsInPy

```bash
git clone https://github.com/soarsmu/BugsInPy ../BugsInPy
```

### 2. Create a virtual environment

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure API key

```bash
cp .env.example .env
# Edit .env and fill in your Anthropic API key
```

The only required key is `CLAUDE_API_KEY` - used by `debug_agent.py` (step 4) to call Claude for diagnosis and fix generation.

### 4. Verify setup

```bash
bugsinpy-checkout --help
```

## Running the Pipeline

### Full pipeline on all bugs

```bash
python3 run_pipeline.py
```

Processes projects in sequence, pausing every 5 bugs to ask whether to continue. Results are saved to `fix_output/<project>/bug<N>/`.

### Options

```
--workspace DIR     Custom workspace directory (default: ../BugsInPy/workspace)
--skip-checkout     Reuse existing checkouts (faster reruns)
--start N           Skip the first N bugs globally (for resuming)
```

## Claude Code Baseline

`run_claude_code.py` evaluates Claude Code (the `claude` CLI) as a zero-shot bug-fixing baseline. It requires the `claude` CLI to be installed and authenticated separately (it does not use `CLAUDE_API_KEY`).

```bash
# All projects
python3 run_claude_code.py

# Single project
python3 run_claude_code.py --project youtube-dl

# Resume from bug N
python3 run_claude_code.py --start 44

# Set per-bug cost budget (default: $1.50)
python3 run_claude_code.py --budget 2.0
```

## Results

Pre-computed results for 86 fully-traced bugs are in `results/`. Each bug directory contains:

| File | Description |
|---|---|
| `diagnosis.md` | LLM-generated root-cause diagnosis and patch |
| `summary.txt` | Pass/fail result and brief summary |
| `trace_condensed.log` | Condensed PySnooper trace |
| `trace_raw.log` | Full raw PySnooper trace |
| `trace_kg` | Knowledge graph (DOT format) |
| `trace_kg.pdf` | Knowledge graph visualization |

Top-level summary files:
- `results/combined_evaluation.json` - per-bug evaluation data for all 142 attempted bugs
- `results/batch_summary.txt` - human-readable batch run log

## File Reference

| File | Purpose |
|---|---|
| `run_pipeline.py` | Main end-to-end pipeline orchestrator |
| `helpers/run_trace.py` | Step 1 - PySnooper trace instrumentation |
| `helpers/trace_condense.py` | Step 2 - Trace condensation / filtering |
| `helpers/build_trace_kg.py` | Step 3 - Knowledge graph construction |
| `helpers/debug_agent.py` | Step 4 - Claude-based diagnosis and fix generation |
| `helpers/run_claude_code.py` | Claude Code CLI baseline (separate evaluation) |
| `.env.example` | API key template |

# AI-for-Research

An evidence-first, local-paper multi-agent system for AI-for-Science research.

The project turns a research question and a local PDF corpus into a traceable research report:

```text
research question
        ↓
planner → local PDF loader → paper reader → hypothesis generator
                                                ↓
                         critical reviewer → scientific director
                                                ↓
                 evidence-backed report + limitations + next experiment
```

The primary demo question is:

> What evidence supports partial representational alignment between human EEG and LLM reasoning states?

This is a research-engineering demo, not an autonomous scientific authority. The system is designed to make model contributions inspectable, source-linked, reproducible, and easy to challenge.

## Why this project

Many multi-agent demos optimize for a fluent final answer. This project optimizes for an auditable path to that answer:

- papers are loaded locally by Python rather than guessed or discovered by an LLM;
- each evidence item keeps its `paper_id` and one-based PDF page;
- agents exchange JSON-shaped state instead of free-form conversation;
- hypotheses are generated only after evidence extraction;
- a critic can flag unsupported claims and trigger at most one bounded repair;
- the final report is blocked unless its citations resolve to loaded evidence;
- live calls write content-addressed cache entries and JSONL trace records;
- replay mode reconstructs a run without contacting model providers.

## Agent architecture

The PDF Loader is deterministic infrastructure. The other five stages are model-backed roles:

| Stage | Provider / model | Responsibility |
| --- | --- | --- |
| Planner | DashScope / Qwen3.8-Max | Decompose the question into subquestions, keywords, and analysis criteria |
| PDF Loader | Python / PyPDF2 | Extract page-aware text from local PDFs; no model call |
| Paper Reader | DashScope / Qwen3.8-Max | Extract concise, page-cited evidence from each paper |
| Hypothesis Generator | Groq / GPT-OSS-120B | Turn evidence into mechanisms and testable predictions |
| Critical Reviewer | Anthropic / Claude Sonnet 4.6 | Find unsupported claims, missing controls, and methodological weaknesses |
| Scientific Director | Anthropic / Claude Sonnet 4.6 | Synthesize the final answer, limitations, and next experiment |

All model-backed stages use the shared provider abstraction in `src/workflow.py`. API keys are read from the local `.env` file or the process environment; they are not required in Git-tracked YAML.

## Shared state and evidence gate

The workflow passes one JSON-serializable `ResearchState` through the pipeline. In addition to the planner's `plan`, it contains:

```python
ResearchState(
    question: str,
    papers: list,
    evidence: list,
    hypotheses: list,
    critique: dict,
    final_report: dict,
)
```

An evidence record must contain:

```json
{
  "claim_id": "E1",
  "claim": "The study reports partial alignment during reasoning",
  "quote": "Original quotation",
  "paper_id": "paper_02",
  "page": 4,
  "confidence": 0.86
}
```

The same contract is represented in [schemas/research_state.schema.json](schemas/research_state.schema.json) and enforced again in [src/state.py](src/state.py). Claims without a known paper and page cannot pass the final report validation. The current Reader stage is called separately for each local paper and requires evidence coverage from at least two papers before hypotheses are generated.

## Interactive demo UI

The local UI is a dependency-light Python server plus static HTML/CSS/JavaScript. It shows:

- LIVE and REPLAY execution modes;
- the six visible pipeline stages, including the deterministic PDF Loader;
- activity events for each paper-reader call;
- aggregated latency and retry information;
- evidence, hypotheses, critical review, final report, and full trace tabs;
- structured objects rendered as readable JSON rather than `[object Object]`;
- failures and incomplete runs surfaced in the interface.

The UI does not display private chain-of-thought. Its timing is provider round-trip latency and its structured result panels show only the output that enters the shared state.

## Repository layout

```text
.
├── data/demo_papers/              # Five local PDFs used by the demo
├── schemas/
│   └── research_state.schema.json # JSON Schema for the shared state
├── src/
│   ├── workflow.py                # Main five-agent orchestration
│   ├── state.py                   # ResearchState and citation validation
│   ├── runtime.py                 # Cache, replay, trace, and report persistence
│   ├── llm_client.py              # Anthropic and OpenAI-compatible transport
│   ├── research_main.py           # CLI for the paper-driven workflow
│   ├── ui_server.py                # Local demo server and progress API
│   ├── config/                    # YAML and .env configuration resolution
│   └── tools/pdf_loader.py        # Local PDF extraction and page chunks
├── ui/
│   ├── index.html                 # Demo UI layout
│   ├── styles.css                 # Visual design
│   └── app.js                     # Polling, rendering, and interactions
├── config.yaml.example            # Non-secret configuration template
├── .env                           # Local secrets; ignored by Git
├── requirements.txt
├── cache/                         # Generated live-call cache; ignored by Git
└── runs/                          # Generated reports and traces; ignored by Git
```

## Quick start

### 1. Create an environment

PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

On macOS/Linux, use `.venv/bin/python` and `.venv/bin/activate` instead.

### 2. Create local configuration

```powershell
Copy-Item config.yaml.example config.yaml
```

`config.yaml` is intentionally ignored by Git. Put live credentials in the root `.env` file:

```dotenv
ANTHROPIC_API_KEY=your_anthropic_key
QWEN_API_KEY=your_dashscope_key
GROQ_API_KEY=your_groq_key
```

`DASHSCOPE_API_KEY` can be used instead of `QWEN_API_KEY`. Never commit `.env`, real keys, or a populated `config.yaml`.

See [MULTI_MODEL_SETUP.md](MULTI_MODEL_SETUP.md) for the current provider routing and credential precedence.

### 3. Start the interactive UI

```powershell
.\.venv\Scripts\python.exe -m src.ui_server --host 127.0.0.1 --port 8765
```

Open <http://127.0.0.1:8765>. After changing Python files, stop and restart this server because it does not hot-reload imported modules.

## CLI workflow

The UI is the intended interview demo, but the same workflow can run from the command line:

```powershell
.\.venv\Scripts\python.exe -m src.research_main `
  --mode live `
  --question "What evidence supports partial representational alignment between human EEG and LLM reasoning states?"
```

After a successful live run, replay the same question and local corpus without provider calls:

```powershell
.\.venv\Scripts\python.exe -m src.research_main --mode replay
```

Replay is content-addressed. The question, paper inputs, model assignment, and state passed to each stage must match the cached live run. Run LIVE once after changing prompts, models, schema, or workflow logic.

Useful options include:

```text
--papers-dir data/demo_papers
--cache-dir cache
--runs-dir runs
--trace-path runs/trace.jsonl
--timeout 45
--max-retries 2
--no-persist
```

## Cache, retry, and trace behavior

Transient provider failures such as rate limits, server errors, and timeouts are retried up to two times. Common model-format failures, including malformed JSON, also receive bounded retry with a stricter JSON-only instruction. There is no unbounded agent-to-agent chat loop.

Each live model call produces a trace record like:

```json
{
  "agent": "critic",
  "model": "claude-sonnet-4-6",
  "latency_ms": 18300,
  "retry_count": 0,
  "status": "success",
  "mode": "live",
  "cache_hit": false
}
```

The default persisted artifacts are:

```text
runs/research_state.json  # Complete validated shared state
runs/final_report.md      # Human-readable report
runs/trace.jsonl          # One record per model call
cache/*.json              # Structured provider results for replay
```

The UI stores each run under `runs/ui/<run_id>/` so that a demo run can be inspected independently.

## Current limitations

- PDF processing is text extraction with PyPDF2; figures, tables, scanned pages, and OCR are not interpreted by the current Reader.
- The primary workflow reads only the PDFs already present in `data/demo_papers`; it does not ask an LLM to discover paper sources.
- Evidence quality still depends on the model's ability to select faithful quotations from extracted text.
- Provider availability, rate limits, quotas, and latency are external to this repository.

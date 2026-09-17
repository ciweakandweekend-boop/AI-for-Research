# Multi-model setup

This file is the provider reference for the current paper-driven workflow. The main project guide is [README.md](README.md).

## Current routing

| Workflow role | Provider | Model | Environment variable |
| --- | --- | --- | --- |
| Planner | DashScope | `qwen3.8-max` | `QWEN_API_KEY` or `DASHSCOPE_API_KEY` |
| Paper Reader | DashScope | `qwen3.8-max` | `QWEN_API_KEY` or `DASHSCOPE_API_KEY` |
| Hypothesis Generator | Groq | `openai/gpt-oss-120b` | `GROQ_API_KEY` |
| Critical Reviewer | Anthropic | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` |
| Scientific Director | Anthropic | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` |

The PDF Loader is local Python infrastructure and does not use an API key.

## Credentials

Use the root `.env` file, which is ignored by Git:

```dotenv
ANTHROPIC_API_KEY=your_anthropic_key
QWEN_API_KEY=your_dashscope_key
GROQ_API_KEY=your_groq_key
```

Do not put real keys in `config.yaml`, `config.yaml.example`, source code, screenshots, logs, or Git history. If a key is exposed, revoke it at the provider and issue a replacement.

The loader accepts `QWEN_API_KEY` as the role-specific key and `DASHSCOPE_API_KEY` as the provider-level fallback. Environment variables take precedence over YAML values.

## Configuration files

- `config.yaml.example` is the safe template committed to the repository.
- `config.yaml` is the local runtime configuration and is ignored by Git.
- `.env` is the local secret file and is ignored by Git.

The per-agent settings include provider, model, base URL, output limit, timeout, and provider-specific request options. The workflow itself keeps the role mapping in `src/workflow.py` so that the orchestration contract remains explicit.

## Offline configuration check

```powershell
.\.venv\Scripts\python.exe -m src.main --config config.yaml --check-config
```

This checks whether configured credentials can be resolved without sending a model request. It does not verify quota, permissions, or provider health.

## Live and replay

Use LIVE after changing any prompt, model, provider, paper corpus, or workflow code:

```powershell
.\.venv\Scripts\python.exe -m src.research_main --mode live
```

After a successful live run, REPLAY uses the structured cache and makes no provider calls:

```powershell
.\.venv\Scripts\python.exe -m src.research_main --mode replay
```

The interactive UI exposes the same two modes. A replay cache miss means that a matching live result does not exist; run LIVE once with the same question and corpus.

## Provider notes

- Qwen is called through DashScope's OpenAI-compatible Chat Completions endpoint.
- GPT-OSS-120B is called through Groq's OpenAI-compatible endpoint.
- Claude is called through the Anthropic Messages API.
- The workflow requests JSON-shaped output from every model stage and validates the result before passing it to the next stage.
- Provider reasoning content is not treated as an agent answer or displayed in the UI.

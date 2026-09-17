"""CLI for the paper-driven multi-agent research workflow."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .workflow import run_workflow


DEFAULT_QUESTION = (
    "What evidence supports partial representational alignment between human "
    "EEG and LLM reasoning states?"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local-paper research workflow")
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument("--mode", choices=("live", "replay"), default="live")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--papers-dir", default="data/demo_papers")
    parser.add_argument("--cache-dir", default="cache")
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument("--trace-path", default=None)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--no-persist", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    state = asyncio.run(
        run_workflow(
            args.question,
            config_path=args.config,
            papers_dir=Path(args.papers_dir),
            mode=args.mode,
            cache_dir=Path(args.cache_dir),
            runs_dir=Path(args.runs_dir),
            trace_path=Path(args.trace_path) if args.trace_path else None,
            timeout=args.timeout,
            max_retries=args.max_retries,
            persist=not args.no_persist,
        )
    )
    print(f"mode={args.mode}")
    print(f"evidence={len(state.evidence)} hypotheses={len(state.hypotheses)}")
    if not args.no_persist:
        print(f"final_report={Path(args.runs_dir) / 'final_report.md'}")
        print(f"state={Path(args.runs_dir) / 'research_state.json'}")
        print(f"trace={Path(args.trace_path) if args.trace_path else Path(args.runs_dir) / 'trace.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

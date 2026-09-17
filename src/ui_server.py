"""Small local web server for the interactive research demo UI.

It intentionally uses only the Python standard library so the interview demo
can start in the existing virtual environment without a frontend dependency.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
import json
from pathlib import Path
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse
import uuid

from .workflow import run_workflow


PROJECT_ROOT = Path(__file__).resolve().parents[1]
UI_ROOT = PROJECT_ROOT / "ui"
DEFAULT_QUESTION = (
    "What evidence supports partial representational alignment between human "
    "EEG and LLM reasoning states?"
)
AGENT_META = {
    "planner": {"name": "Planner", "model": "Qwen3.8-Max", "accent": "violet"},
    "loader": {"name": "PDF Loader", "model": "Python / PyPDF2", "accent": "cyan"},
    "reader": {"name": "Paper Reader", "model": "Qwen3.8-Max", "accent": "blue"},
    "hypothesis": {"name": "Hypothesis Generator", "model": "GPT-OSS-120B", "accent": "orange"},
    "critic": {"name": "Critical Reviewer", "model": "Claude Sonnet 4.6", "accent": "pink"},
    "director": {"name": "Scientific Director", "model": "Claude Sonnet 4.6", "accent": "green"},
}


@dataclass
class DemoRun:
    run_id: str
    question: str
    mode: str
    cache_dir: Path
    runs_dir: Path
    status: str = "queued"
    phase: str = "queued"
    phase_status: str = "queued"
    events: list[dict[str, Any]] = field(default_factory=list)
    final_state: dict[str, Any] | None = None
    error: str | None = None
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None


RUNS: dict[str, DemoRun] = {}
RUNS_LOCK = threading.RLock()


def _read_trace(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
    except (OSError, json.JSONDecodeError):
        return records
    return records


def _job_payload(job: DemoRun) -> dict[str, Any]:
    trace = _read_trace(job.runs_dir / "trace.jsonl")
    with RUNS_LOCK:
        return {
            "run_id": job.run_id,
            "question": job.question,
            "mode": job.mode,
            "status": job.status,
            "phase": job.phase,
            "phase_status": job.phase_status,
            "events": list(job.events),
            "trace": trace,
            "state": job.final_state,
            "error": job.error,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "paths": {
                "report": str(job.runs_dir / "final_report.md"),
                "state": str(job.runs_dir / "research_state.json"),
                "trace": str(job.runs_dir / "trace.jsonl"),
            },
        }


def _start_run(payload: dict[str, Any]) -> DemoRun:
    question = str(payload.get("question") or DEFAULT_QUESTION).strip()
    mode = payload.get("mode", "live")
    if mode not in {"live", "replay"}:
        raise ValueError("mode must be live or replay")
    if not question:
        raise ValueError("question cannot be empty")
    try:
        timeout = float(payload.get("timeout", 45.0))
        max_retries = int(payload.get("retries", 2))
    except (TypeError, ValueError) as exc:
        raise ValueError("timeout and retries must be numeric") from exc
    if timeout <= 0 or timeout > 120:
        raise ValueError("timeout must be between 1 and 120 seconds")
    if max_retries < 0 or max_retries > 2:
        raise ValueError("retries must be between 0 and 2")

    run_id = f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    cache_dir = PROJECT_ROOT / "cache"
    runs_dir = PROJECT_ROOT / "runs" / "ui" / run_id
    job = DemoRun(
        run_id=run_id,
        question=question,
        mode=mode,
        cache_dir=cache_dir,
        runs_dir=runs_dir,
    )
    with RUNS_LOCK:
        RUNS[run_id] = job

    def on_progress(event: dict[str, Any]) -> None:
        with RUNS_LOCK:
            job.phase = str(event.get("phase", job.phase))
            job.phase_status = str(event.get("status", job.phase_status))
            job.events.append(dict(event))

    def worker() -> None:
        with RUNS_LOCK:
            job.status = "running"
        try:
            state = asyncio.run(
                run_workflow(
                    question,
                    mode=mode,
                    cache_dir=cache_dir,
                    runs_dir=runs_dir,
                    trace_path=runs_dir / "trace.jsonl",
                    timeout=timeout,
                    max_retries=max_retries,
                    progress_callback=on_progress,
                )
            )
            with RUNS_LOCK:
                job.final_state = state.to_dict()
                job.status = "completed"
                job.phase = "pipeline"
                job.phase_status = "completed"
                job.finished_at = time.time()
        except Exception as exc:  # surfaced in the UI; no hidden background failure
            with RUNS_LOCK:
                job.status = "error"
                job.phase_status = "error"
                if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
                    job.error = f"{job.phase.title()} timed out after {timeout:g} seconds"
                else:
                    job.error = f"{type(exc).__name__}: {exc}"
                job.finished_at = time.time()

    threading.Thread(target=worker, name=f"research-{run_id}", daemon=True).start()
    return job


class DemoHandler(BaseHTTPRequestHandler):
    server_version = "ResearchDemoUI/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        # Keep the terminal focused on the server URL and workflow errors.
        return

    def _send_bytes(self, data: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, value: Any, status: int = 200) -> None:
        self._send_bytes(
            json.dumps(value, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
            status,
        )

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/" or path == "/index.html":
            self._serve_file(UI_ROOT / "index.html", "text/html; charset=utf-8")
            return
        if path == "/styles.css":
            self._serve_file(UI_ROOT / "styles.css", "text/css; charset=utf-8")
            return
        if path == "/app.js":
            self._serve_file(UI_ROOT / "app.js", "text/javascript; charset=utf-8")
            return
        if path == "/api/health":
            self._send_json({"ok": True, "runs": len(RUNS)})
            return
        if path.startswith("/api/run/"):
            run_id = path.removeprefix("/api/run/").strip("/")
            with RUNS_LOCK:
                job = RUNS.get(run_id)
            if job is None:
                self._send_json({"error": "run not found"}, 404)
            else:
                self._send_json(_job_payload(job))
            return
        self._send_json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/run":
            self._send_json({"error": "not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            job = _start_run(payload)
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json({"error": str(exc)}, 400)
            return
        self._send_json({"run_id": job.run_id, "status": job.status}, 202)

    def _serve_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            self._send_json({"error": "UI asset missing"}, 404)
            return
        self._send_bytes(path.read_bytes(), content_type)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Start the local research demo UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), DemoHandler)
    print(f"Research demo UI: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping UI")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

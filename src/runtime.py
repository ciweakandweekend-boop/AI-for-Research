"""Runtime support for cache/replay execution and JSONL tracing."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


CACHE_FORMAT_VERSION = 2


class CacheMissError(FileNotFoundError):
    """Raised when replay mode has no result for the requested input."""


def canonical_json(value: Any) -> str:
    """Serialize JSON-shaped values deterministically for cache keys."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class AgentCache:
    """Content-addressed cache for structured agent outputs."""

    def __init__(self, directory: str | Path = "cache") -> None:
        self.directory = Path(directory)

    def key(self, agent_name: str, model: str, input_state: Mapping[str, Any]) -> str:
        payload = {
            "cache_format": CACHE_FORMAT_VERSION,
            "agent": agent_name,
            "model": model,
            "input": input_state,
        }
        return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()

    def path_for(self, agent_name: str, cache_key: str) -> Path:
        safe_agent = "".join(char if char.isalnum() or char in "_-" else "_" for char in agent_name)
        return self.directory / f"{safe_agent}_{cache_key}.json"

    def save(
        self,
        *,
        agent_name: str,
        model: str,
        cache_key: str,
        output: Mapping[str, Any],
    ) -> Path:
        path = self.path_for(agent_name, cache_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "cache_format": CACHE_FORMAT_VERSION,
            "agent": agent_name,
            "model": model,
            "cache_key": cache_key,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "output": dict(output),
        }
        path.write_text(
            json.dumps(entry, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return path

    def load(self, *, agent_name: str, model: str, cache_key: str) -> dict[str, Any]:
        path = self.path_for(agent_name, cache_key)
        if not path.exists():
            raise CacheMissError(
                f"No replay cache for {agent_name}; expected {path}"
            )
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CacheMissError(f"Unreadable replay cache: {path}") from exc
        if (
            not isinstance(entry, dict)
            or entry.get("cache_format") != CACHE_FORMAT_VERSION
            or entry.get("agent") != agent_name
            or entry.get("model") != model
            or entry.get("cache_key") != cache_key
            or not isinstance(entry.get("output"), dict)
        ):
            raise CacheMissError(f"Invalid replay cache entry: {path}")
        return entry["output"]


class TraceLogger:
    """Append one JSON object per agent call to a trace file."""

    def __init__(self, path: str | Path = "runs/trace.jsonl") -> None:
        self.path = Path(path) if path else None

    def record(
        self,
        *,
        agent: str,
        model: str,
        latency_ms: int,
        retry_count: int,
        status: str,
        mode: str,
        cache_hit: bool = False,
        error: str | None = None,
    ) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent": agent,
            "model": model,
            "latency_ms": max(0, int(latency_ms)),
            "retry_count": retry_count,
            "status": status,
            "mode": mode,
            "cache_hit": cache_hit,
        }
        if error:
            record["error"] = error
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _markdown_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        return "\n".join(f"- {item}" for item in value)
    if isinstance(value, Mapping):
        return "```json\n" + json.dumps(value, ensure_ascii=False, indent=2) + "\n```"
    return str(value)


def render_final_report(state: Any) -> str:
    """Render the validated final report without losing its citations."""

    report = state.final_report
    lines = [f"# {report.get('title', 'Research Report')}", ""]
    lines.extend(["## Summary", "", _markdown_value(report.get("summary", "")), ""])
    lines.extend(["## Evidence", ""])
    for citation in report.get("evidence", []):
        claim_id = citation.get("claim_id", "unknown")
        paper_id = citation.get("paper_id", "unknown")
        page = citation.get("page", "?")
        quote = citation.get("quote", "")
        lines.append(f"- **{claim_id}** — `{paper_id}`, p. {page}: {quote}")
    if not report.get("evidence"):
        lines.append("- No validated evidence citations were returned.")
    lines.extend(["", "## Limitations", "", _markdown_value(report.get("limitations", [])), ""])
    lines.extend([
        "## Next experiment",
        "",
        _markdown_value(report.get("next_experiment", "")),
        "",
    ])
    if state.critique:
        lines.extend(["## Critical review", "", _markdown_value(state.critique), ""])
    return "\n".join(lines).rstrip() + "\n"


def persist_outputs(state: Any, runs_dir: str | Path = "runs") -> dict[str, Path]:
    """Persist the complete state and human-readable final report."""

    root = Path(runs_dir)
    root.mkdir(parents=True, exist_ok=True)
    state_path = root / "research_state.json"
    report_path = root / "final_report.md"
    state_path.write_text(state.to_json(indent=2), encoding="utf-8")
    report_path.write_text(render_final_report(state), encoding="utf-8")
    return {"state": state_path, "report": report_path}


__all__ = [
    "AgentCache",
    "CacheMissError",
    "TraceLogger",
    "canonical_json",
    "persist_outputs",
    "render_final_report",
]

"""Sequential five-agent workflow for the local-paper research demo.

The workflow has one shared state and one structured response contract per
role.  Provider details live in the small live runner below; agents themselves
only see JSON-shaped state and paper chunks.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from datetime import datetime, timezone
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TYPE_CHECKING

from .state import ResearchState, StateValidationError
from .tools.pdf_loader import PaperChunk, load_papers
from .runtime import AgentCache, CacheMissError, TraceLogger, persist_outputs

if TYPE_CHECKING:
    from .llm_client import LLMClient


class WorkflowError(RuntimeError):
    """Raised when an agent does not return the required structured output."""


AGENT_ORDER = ("planner", "reader", "hypothesis", "critic", "director")
ROLE_PROVIDERS = {
    "planner": "dashscope",       # Qwen3.8-Max
    "reader": "dashscope",        # Qwen3.8-Max
    "hypothesis": "groq",         # GPT-OSS-120B
    "critic": "anthropic",       # Claude Sonnet 4.6
    "director": "anthropic",      # Claude Sonnet 4.6
}
ROLE_CONFIG_NAMES = {
    "planner": "Planner",
    "reader": "Paper Reader",
    "hypothesis": "Hypothesis Generator",
    "critic": "Critical Reviewer",
    "director": "Scientific Director",
}
MODEL_BY_ROLE = {
    "planner": "qwen3.8-max",
    "reader": "qwen3.8-max",
    "hypothesis": "openai/gpt-oss-120b",
    "critic": "claude-sonnet-4-6",
    "director": "claude-sonnet-4-6",
}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _parse_json_object(text: str, *, agent_name: str) -> dict[str, Any]:
    """Parse a JSON object, tolerating a markdown code fence around it."""

    if not isinstance(text, str) or not text.strip():
        raise WorkflowError(f"{agent_name} returned empty output")
    candidate = text.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        # Models occasionally add one sentence before the JSON.  Decode the
        # first complete object without accepting arbitrary trailing prose.
        decoder = json.JSONDecoder()
        start = candidate.find("{")
        if start < 0:
            raise WorkflowError(f"{agent_name} did not return a JSON object") from None
        try:
            value, end = decoder.raw_decode(candidate[start:])
        except json.JSONDecodeError as exc:
            raise WorkflowError(f"{agent_name} returned malformed JSON") from exc
        if candidate[start + end :].strip():
            # A valid object plus prose is still usable, but the prose is not
            # allowed to become part of shared state.
            pass
    if not isinstance(value, dict):
        raise WorkflowError(f"{agent_name} must return a JSON object")
    return value


def _structured_result(value: Any, *, agent_name: str) -> dict[str, Any] | ResearchState:
    if isinstance(value, ResearchState):
        return value
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        return _parse_json_object(value, agent_name=agent_name)
    raise WorkflowError(f"{agent_name} returned an unsupported result type")


def _paper_ids(state: ResearchState) -> set[str]:
    return {
        str(paper["paper_id"])
        for paper in state.papers
        if isinstance(paper, Mapping) and paper.get("paper_id")
    }


def _evidence_by_id(state: ResearchState) -> dict[str, dict[str, Any]]:
    return {
        evidence["claim_id"]: evidence
        for evidence in state.evidence
        if isinstance(evidence, Mapping) and isinstance(evidence.get("claim_id"), str)
    }


def _normalise_evidence(output: Mapping[str, Any]) -> list[dict[str, Any]]:
    values = output.get("evidence", output.get("claims", []))
    if not isinstance(values, list):
        raise WorkflowError("reader.evidence must be an array")
    normalised: list[dict[str, Any]] = []
    for index, value in enumerate(values, start=1):
        if not isinstance(value, Mapping):
            raise WorkflowError(f"reader.evidence[{index - 1}] must be an object")
        item = dict(value)
        item.setdefault("claim_id", f"E{index}")
        # Do not invent a source or page.  The state validator will reject it.
        if isinstance(item.get("page"), str) and item["page"].isdigit():
            item["page"] = int(item["page"])
        try:
            item["confidence"] = float(item["confidence"])
        except (KeyError, TypeError, ValueError) as exc:
            raise WorkflowError(
                f"reader.evidence[{index - 1}] must include numeric confidence"
            ) from exc
        normalised.append(item)
    return normalised


def _normalise_hypotheses(output: Mapping[str, Any]) -> list[dict[str, Any]]:
    values = output.get("hypotheses", output.get("claims", []))
    if not isinstance(values, list):
        raise WorkflowError("hypothesis.hypotheses must be an array")
    result: list[dict[str, Any]] = []
    for index, value in enumerate(values, start=1):
        if not isinstance(value, Mapping):
            raise WorkflowError(f"hypothesis.hypotheses[{index - 1}] must be an object")
        item = dict(value)
        item.setdefault("hypothesis_id", f"H{index}")
        item.setdefault("evidence_ids", [])
        result.append(item)
    return result


def _normalise_final_report(
    output: Mapping[str, Any],
    *,
    state: ResearchState,
) -> dict[str, Any]:
    report = dict(output.get("final_report", output))
    if not isinstance(report, dict):
        raise WorkflowError("director.final_report must be an object")
    if "summary" not in report and "answer" in report:
        report["summary"] = report["answer"]
    if "next_experiment" not in report and "next_experiments" in report:
        report["next_experiment"] = report["next_experiments"]
    if "limitations" not in report and "limitations_and_caveats" in report:
        report["limitations"] = report["limitations_and_caveats"]

    evidence_by_id = _evidence_by_id(state)
    citations = report.get("evidence")
    if citations is None:
        citations = report.get("evidence_ids", [])
    if not isinstance(citations, list):
        raise WorkflowError("director.evidence must be an array")

    enriched: list[dict[str, Any]] = []
    for index, citation in enumerate(citations):
        if isinstance(citation, str):
            citation = {"claim_id": citation}
        if not isinstance(citation, Mapping):
            raise WorkflowError(f"director.evidence[{index}] must be an object or claim_id")
        item = dict(citation)
        claim_id = item.get("claim_id", item.get("evidence_id"))
        if claim_id in evidence_by_id:
            source = evidence_by_id[claim_id]
            item.setdefault("claim_id", claim_id)
            item.setdefault("paper_id", source["paper_id"])
            item.setdefault("page", source["page"])
            item.setdefault("quote", source["quote"])
        enriched.append(item)
    report["evidence"] = enriched
    return report


def _apply_agent_output(
    agent_name: str,
    state: ResearchState,
    value: Any,
) -> ResearchState:
    result = _structured_result(value, agent_name=agent_name)
    if isinstance(result, ResearchState):
        result.validate()
        return result

    if agent_name == "planner":
        plan = result.get("plan", result)
        if not isinstance(plan, Mapping):
            raise WorkflowError("planner must return a plan object")
        state.plan = dict(plan)
    elif agent_name == "reader":
        state.evidence = _normalise_evidence(result)
    elif agent_name == "hypothesis":
        state.hypotheses = _normalise_hypotheses(result)
    elif agent_name == "critic":
        critique = result.get("critique", result)
        if not isinstance(critique, Mapping):
            raise WorkflowError("critic must return a critique object")
        state.critique = dict(critique)
    elif agent_name == "director":
        state.final_report = _normalise_final_report(result, state=state)
    else:
        raise WorkflowError(f"unknown agent: {agent_name}")

    try:
        state.validate()
    except StateValidationError as exc:
        raise WorkflowError(f"{agent_name} produced invalid structured output: {exc}") from exc
    return state


def _prompt_for(agent_name: str, state: ResearchState) -> tuple[str, dict[str, Any]]:
    """Return a role-specific JSON-only system prompt and input payload."""

    common = (
        "You are one stage in a scientific research workflow. Return only one "
        "valid JSON object, with no markdown and no commentary. Never invent a "
        "paper_id, page, quotation, or result."
    )
    if agent_name == "planner":
        return (
            common
            + " Output keys: subquestions (array of strings), keywords (array of strings), "
            "analysis_criteria (array of strings).",
            {"question": state.question},
        )
    if agent_name == "reader":
        return (
            common
            + " Extract only directly supported evidence. Output {evidence: [...]} where "
            "each item has claim_id, claim, quote, paper_id, page, confidence. "
            "page is the one-based page supplied with the chunk and confidence is 0..1.",
            {
                "question": state.question,
                "plan": state.plan,
                "paper_chunks": state.papers,
            },
        )
    if agent_name == "hypothesis":
        return (
            common
            + " Generate testable hypotheses only from the evidence. Output "
            "{hypotheses: [{hypothesis_id, hypothesis, mechanism, predictions, evidence_ids}]}.",
            {
                "question": state.question,
                "evidence": state.evidence,
                "critique": state.critique,
            },
        )
    if agent_name == "critic":
        return (
            common
            + " Audit every hypothesis against the evidence. Output "
            "{status: 'pass'|'revise'|'reject', findings: [...], unsupported_claims: [...], "
            "required_repairs: [...]}. Identify evidence_ids when possible.",
            {
                "question": state.question,
                "evidence": state.evidence,
                "hypotheses": state.hypotheses,
            },
        )
    if agent_name == "director":
        return (
            common
            + " Write the final scientific report as an object with title, summary, "
            "evidence (citation objects with claim_id, paper_id, page), limitations, "
            "and next_experiment. Every report claim must cite known evidence.",
            {
                "question": state.question,
                "plan": state.plan,
                "evidence": state.evidence,
                "hypotheses": state.hypotheses,
                "critique": state.critique,
            },
        )
    raise WorkflowError(f"unknown agent: {agent_name}")


@dataclass
class _LiveAgentRunner:
    """Adapter from the existing provider clients to the shared call contract."""

    config_path: str = "config.yaml"
    request_timeout: float = 45.0

    def __post_init__(self) -> None:
        # Keep live-provider imports lazy so PDF loading and mock tests do not
        # require every SDK to be installed.
        from .config import LabConfig

        self.config = LabConfig(self.config_path)
        self._clients: dict[str, tuple[Any, dict[str, Any]]] = {}

    def _client_for(self, agent_name: str) -> tuple[Any, dict[str, Any]]:
        provider = ROLE_PROVIDERS[agent_name]
        if agent_name in self._clients:
            return self._clients[agent_name]
        configured_name = ROLE_CONFIG_NAMES[agent_name].casefold()
        configured = next(
            (
                agent for agent in self.config.agents
                if str(agent.get("name", "")).casefold() == configured_name
            ),
            None,
        )
        if configured is None:
            # Keep compatibility with older configs that used Lea/Emmy/etc.
            configured = next(
                (agent for agent in self.config.agents if agent.get("provider") == provider),
                None,
            )
        if configured is None:
            raise WorkflowError(
                f"No configured agent uses provider '{provider}' for role '{agent_name}'"
            )
        settings = self.config.agent_settings(configured)
        if not settings["api_key"]:
            raise WorkflowError(
                f"Missing API key for {agent_name}; use .env/environment variables or config"
            )
        from .llm_client import LLMClient

        client = LLMClient(
            api_key=settings["api_key"],
            provider=settings["provider"],
            base_url=settings["base_url"],
            timeout=self.request_timeout,
            extra_body=settings["extra_body"],
        )
        self._clients[agent_name] = (client, settings)
        return client, settings

    async def call(self, agent_name: str, state: ResearchState) -> dict[str, Any]:
        if agent_name not in ROLE_PROVIDERS:
            raise WorkflowError(f"unknown agent: {agent_name}")
        client, settings = self._client_for(agent_name)
        system, payload = _prompt_for(agent_name, state)
        configured_prompt = settings.get("system_prompt", "")
        if configured_prompt:
            system += f"\nAdditional role guidance:\n{configured_prompt}"
        response = await asyncio.to_thread(
            client.create,
            model=settings["model"],
            system=system,
            messages=[{"role": "user", "content": _json(payload)}],
            max_tokens=settings["max_tokens"],
        )
        text = "\n".join(
            block.text for block in response.content if getattr(block, "text", None)
        )
        return _parse_json_object(text, agent_name=agent_name)


async def call_agent(
    agent_name: str,
    state: ResearchState,
    *,
    config_path: str = "config.yaml",
    runner: _LiveAgentRunner | None = None,
    base_call: AgentCall | None = None,
    mode: str = "live",
    cache_dir: str | Path = "cache",
    trace_path: str | Path | None = "runs/trace.jsonl",
    cache: AgentCache | None = None,
    trace_logger: TraceLogger | None = None,
    timeout: float = 45.0,
    max_retries: int = 2,
    retry_delay: float = 0.25,
) -> dict[str, Any]:
    """Call one role with bounded retry, cache/replay, timeout and tracing.

    ``mode='live'`` calls the provider and writes a structured cache entry.
    ``mode='replay'`` reads the matching entry and never constructs a provider
    client.  A custom ``base_call`` is useful for offline tests while retaining
    exactly the same runtime guarantees.
    """

    if agent_name not in AGENT_ORDER:
        raise WorkflowError(f"unknown agent: {agent_name}")
    if mode not in {"live", "replay"}:
        raise ValueError("mode must be 'live' or 'replay'")
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if not isinstance(max_retries, int) or max_retries < 0:
        raise ValueError("max_retries must be a non-negative integer")
    if retry_delay < 0:
        raise ValueError("retry_delay must be non-negative")

    model = MODEL_BY_ROLE[agent_name]
    cache_store = cache or AgentCache(cache_dir)
    tracer = trace_logger or TraceLogger(trace_path)
    cache_input = state.to_dict(validate=False)
    cache_key = cache_store.key(agent_name, model, cache_input)

    if mode == "replay":
        started = time.perf_counter()
        try:
            output = cache_store.load(
                agent_name=agent_name,
                model=model,
                cache_key=cache_key,
            )
        except CacheMissError as exc:
            tracer.record(
                agent=agent_name,
                model=model,
                latency_ms=_elapsed_ms(started),
                retry_count=0,
                status="error",
                mode=mode,
                error=str(exc),
            )
            raise WorkflowError(str(exc)) from exc
        tracer.record(
            agent=agent_name,
            model=model,
            latency_ms=_elapsed_ms(started),
            retry_count=0,
            status="success",
            mode=mode,
            cache_hit=True,
        )
        return output

    active_runner = runner
    if base_call is None:
        active_runner = active_runner or _LiveAgentRunner(
            config_path,
            request_timeout=timeout,
        )

    async def invoke() -> Any:
        if base_call is not None:
            result = base_call(agent_name, state)
            return await result if inspect.isawaitable(result) else result
        return await active_runner.call(agent_name, state)

    retry_count = 0
    while True:
        started = time.perf_counter()
        try:
            raw_output = await asyncio.wait_for(invoke(), timeout=timeout)
            if isinstance(raw_output, str):
                output = _parse_json_object(raw_output, agent_name=agent_name)
            elif isinstance(raw_output, Mapping):
                output = dict(raw_output)
            else:
                raise WorkflowError(
                    f"{agent_name} returned an unsupported result type"
                )
            cache_store.save(
                agent_name=agent_name,
                model=model,
                cache_key=cache_key,
                output=output,
            )
            tracer.record(
                agent=agent_name,
                model=model,
                latency_ms=_elapsed_ms(started),
                retry_count=retry_count,
                status="success",
                mode=mode,
            )
            return output
        except Exception as exc:
            retryable = _is_retryable(exc)
            if retryable and retry_count < max_retries:
                retry_count += 1
                if retry_delay:
                    await asyncio.sleep(retry_delay * (2 ** (retry_count - 1)))
                continue
            tracer.record(
                agent=agent_name,
                model=model,
                latency_ms=_elapsed_ms(started),
                retry_count=retry_count,
                status="error",
                mode=mode,
                error=str(exc),
            )
            raise


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _is_retryable(error: BaseException) -> bool:
    status_code = getattr(error, "status_code", None)
    if isinstance(status_code, int) and (status_code in {408, 429} or status_code >= 500):
        return True
    error_name = error.__class__.__name__.lower()
    return (
        isinstance(error, (TimeoutError, asyncio.TimeoutError))
        or "timeout" in error_name
        or bool(getattr(error, "retryable", False))
    )


AgentCall = Callable[[str, ResearchState], Awaitable[Any] | Any]
PaperLoader = Callable[..., list[PaperChunk]]
ProgressCallback = Callable[[dict[str, Any]], None]


class ResearchWorkflow:
    """Run the five roles exactly once, with bounded runtime controls."""

    def __init__(
        self,
        *,
        config_path: str = "config.yaml",
        papers_dir: str | Path = "data/demo_papers",
        agent_call: AgentCall | None = None,
        paper_loader: PaperLoader = load_papers,
        max_reader_chars: int = 120_000,
        max_hypothesis_repairs: int = 1,
        mode: str = "live",
        cache_dir: str | Path = "cache",
        runs_dir: str | Path = "runs",
        trace_path: str | Path | None = None,
        timeout: float = 45.0,
        max_retries: int = 2,
        retry_delay: float = 0.25,
        persist: bool = True,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        if max_hypothesis_repairs not in (0, 1):
            raise ValueError("max_hypothesis_repairs must be 0 or 1")
        if max_reader_chars < 1:
            raise ValueError("max_reader_chars must be positive")
        if mode not in {"live", "replay"}:
            raise ValueError("mode must be 'live' or 'replay'")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if not isinstance(max_retries, int) or max_retries < 0 or max_retries > 2:
            raise ValueError("max_retries must be an integer between 0 and 2")
        if retry_delay < 0:
            raise ValueError("retry_delay must be non-negative")
        self.config_path = config_path
        self.papers_dir = papers_dir
        self.agent_call = agent_call
        self.paper_loader = paper_loader
        self.max_reader_chars = max_reader_chars
        self.max_hypothesis_repairs = max_hypothesis_repairs
        self.mode = mode
        self.cache_dir = cache_dir
        self.runs_dir = runs_dir
        self.trace_path = trace_path
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.persist = persist
        self.progress_callback = progress_callback
        self.output_paths: dict[str, Path] = {}

    def _emit(self, phase: str, status: str, state: ResearchState, **extra: Any) -> None:
        """Emit UI-safe progress without making callbacks part of the state."""

        if self.progress_callback is None:
            return
        event: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "phase": phase,
            "status": status,
            "question": state.question,
            "counts": {
                "papers": len({
                    paper.get("paper_id") for paper in state.papers
                    if isinstance(paper, Mapping)
                }),
                "evidence": len(state.evidence),
                "hypotheses": len(state.hypotheses),
            },
        }
        event.update(extra)
        try:
            self.progress_callback(event)
        except Exception:
            # A visual monitor must never break a scientific run.
            pass

    async def _invoke(
        self,
        agent_name: str,
        state: ResearchState,
        *,
        base_call: AgentCall | None,
        runner: _LiveAgentRunner | None,
        cache: AgentCache,
        trace_logger: TraceLogger,
    ) -> Any:
        return await call_agent(
            agent_name,
            state,
            config_path=self.config_path,
            runner=runner,
            base_call=base_call,
            mode=self.mode,
            cache=cache,
            trace_logger=trace_logger,
            timeout=self.timeout,
            max_retries=self.max_retries,
            retry_delay=self.retry_delay,
        )

    def _load_chunks(self) -> list[PaperChunk]:
        return self.paper_loader(self.papers_dir)

    def _set_papers(self, state: ResearchState, chunks: list[PaperChunk]) -> None:
        state.papers = [
            chunk.to_dict() if isinstance(chunk, PaperChunk) else dict(chunk)
            for chunk in chunks
        ]
        # Prompt size is bounded at the reader boundary, but keep all chunks in
        # state so a future chunk-wise reader can replay the exact input.
        state.validate()

    async def run(self, question: str) -> ResearchState:
        state = ResearchState(question=question)
        runner = None
        if self.mode == "live" and self.agent_call is None:
            runner = _LiveAgentRunner(
                self.config_path,
                request_timeout=self.timeout,
            )
        base_call = self.agent_call
        cache = AgentCache(self.cache_dir)
        trace_path = self.trace_path or (Path(self.runs_dir) / "trace.jsonl")
        trace_logger = TraceLogger(trace_path)

        # 1. Planner
        self._emit("planner", "running", state, label="Planning research question")
        state = _apply_agent_output(
            "planner",
            state,
            await self._invoke(
                "planner", state, base_call=base_call, runner=runner,
                cache=cache, trace_logger=trace_logger,
            ),
        )
        self._emit(
            "planner", "completed", state, label="Plan ready",
            result={
                "subquestions": state.plan.get("subquestions", []),
                "keywords": state.plan.get("keywords", []),
                "analysis_criteria": state.plan.get("analysis_criteria", []),
            },
        )

        # 2. Local PDF loader (no model call and no paper search)
        self._emit("loader", "running", state, label="Reading local PDF corpus")
        self._set_papers(state, self._load_chunks())
        if not state.papers:
            raise WorkflowError(f"No extractable PDF text found in {self.papers_dir}")
        self._emit(
            "loader", "completed", state, label="PDF corpus indexed",
            result={
                "paper_ids": sorted({paper.get("paper_id") for paper in state.papers}),
                "chunks": len(state.papers),
            },
        )

        # 3. Paper Reader
        self._emit("reader", "running", state, label="Extracting page-level evidence")
        reader_state = ResearchState.from_dict(state.to_dict(validate=False), validate=False)
        reader_state.papers = _bounded_reader_chunks(state.papers, self.max_reader_chars)
        state = _apply_agent_output(
            "reader",
            state,
            await self._invoke(
                "reader", reader_state, base_call=base_call, runner=runner,
                cache=cache, trace_logger=trace_logger,
            ),
        )
        self._emit(
            "reader", "completed", state, label="Evidence extracted",
            result={"evidence": state.evidence},
        )

        # 4. Hypothesis Generator
        self._emit("hypothesis", "running", state, label="Generating testable hypotheses")
        state = _apply_agent_output(
            "hypothesis",
            state,
            await self._invoke(
                "hypothesis", state, base_call=base_call, runner=runner,
                cache=cache, trace_logger=trace_logger,
            ),
        )
        self._emit(
            "hypothesis", "completed", state, label="Hypotheses generated",
            result={"hypotheses": state.hypotheses},
        )

        # 5. Critical Reviewer
        self._emit("critic", "running", state, label="Auditing claims and assumptions")
        state = _apply_agent_output(
            "critic",
            state,
            await self._invoke(
                "critic", state, base_call=base_call, runner=runner,
                cache=cache, trace_logger=trace_logger,
            ),
        )
        self._emit(
            "critic", "completed", state, label="Critical review complete",
            result=state.critique,
        )

        # A critique can trigger one bounded hypothesis repair.  There is no
        # loop: the director is always the final model stage.
        if (
            self.max_hypothesis_repairs == 1
            and str(state.critique.get("status", "")).lower() in {"revise", "modify", "repair"}
        ):
            state.critique["repair_attempted"] = True
            self._emit("hypothesis", "repairing", state, label="Applying one bounded repair")
            state = _apply_agent_output(
                "hypothesis",
                state,
                await self._invoke(
                    "hypothesis", state, base_call=base_call, runner=runner,
                    cache=cache, trace_logger=trace_logger,
                ),
            )
            self._emit(
                "hypothesis", "repaired", state, label="Hypothesis repair complete",
                result={"hypotheses": state.hypotheses},
            )

        # 6. Scientific Director
        self._emit("director", "running", state, label="Synthesizing final report")
        state = _apply_agent_output(
            "director",
            state,
            await self._invoke(
                "director", state, base_call=base_call, runner=runner,
                cache=cache, trace_logger=trace_logger,
            ),
        )
        state.validate(require_final_report=True)
        if self.persist:
            self.output_paths = persist_outputs(state, self.runs_dir)
        self._emit(
            "director", "completed", state, label="Final report ready",
            result=state.final_report,
        )
        self._emit("pipeline", "completed", state, label="Research run complete")
        return state


def _bounded_reader_chunks(
    papers: list[dict[str, Any]],
    max_chars: int,
) -> list[dict[str, Any]]:
    # Keep representation from all local papers when a provider context limit
    # requires truncation; taking the first N chunks would silently omit later
    # papers from the scientific comparison.
    groups: dict[str, list[dict[str, Any]]] = {}
    for paper in papers:
        groups.setdefault(str(paper.get("paper_id", "unknown")), []).append(paper)
    if not groups:
        return []

    per_paper = max(1, max_chars // len(groups))
    selected: list[dict[str, Any]] = []
    used = 0
    for group in groups.values():
        group_used = 0
        for paper in group:
            if used >= max_chars or group_used >= per_paper:
                break
            item = dict(paper)
            text = str(item.get("text", ""))
            remaining = min(max_chars - used, per_paper - group_used)
            item["text"] = text[:remaining]
            if item["text"]:
                selected.append(item)
                used += len(item["text"])
                group_used += len(item["text"])
    return selected


async def run_workflow(
    question: str,
    *,
    config_path: str = "config.yaml",
    papers_dir: str | Path = "data/demo_papers",
    agent_call: AgentCall | None = None,
    paper_loader: PaperLoader = load_papers,
    max_reader_chars: int = 120_000,
    max_hypothesis_repairs: int = 1,
    mode: str = "live",
    cache_dir: str | Path = "cache",
    runs_dir: str | Path = "runs",
    trace_path: str | Path | None = None,
    timeout: float = 45.0,
    max_retries: int = 2,
    retry_delay: float = 0.25,
    persist: bool = True,
    progress_callback: ProgressCallback | None = None,
) -> ResearchState:
    """Convenience coroutine for running the local research workflow."""

    workflow = ResearchWorkflow(
        config_path=config_path,
        papers_dir=papers_dir,
        agent_call=agent_call,
        paper_loader=paper_loader,
        max_reader_chars=max_reader_chars,
        max_hypothesis_repairs=max_hypothesis_repairs,
        mode=mode,
        cache_dir=cache_dir,
        runs_dir=runs_dir,
        trace_path=trace_path,
        timeout=timeout,
        max_retries=max_retries,
        retry_delay=retry_delay,
        persist=persist,
        progress_callback=progress_callback,
    )
    return await workflow.run(question)


__all__ = [
    "AGENT_ORDER",
    "MODEL_BY_ROLE",
    "ResearchWorkflow",
    "WorkflowError",
    "call_agent",
    "run_workflow",
]

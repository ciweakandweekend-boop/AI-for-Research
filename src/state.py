"""Structured state shared by the paper-driven research agents.

The workflow deliberately passes plain JSON-shaped data between agents.  The
dataclass in this module is only a small convenience wrapper around that data;
it does not contain provider-specific objects or conversation history.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
from typing import Any, Mapping


class StateValidationError(ValueError):
    """Raised when state would violate the research-state contract."""


# This is kept in Python as well as in ``schemas/research_state.schema.json``
# so callers do not need a JSON-schema package just to construct a state.
RESEARCH_STATE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "ResearchState",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "question",
        "papers",
        "evidence",
        "hypotheses",
        "critique",
        "final_report",
    ],
    "properties": {
        "question": {"type": "string", "minLength": 1},
        "plan": {
            "type": "object",
            "additionalProperties": True,
        },
        "papers": {
            "type": "array",
            "items": {"$ref": "#/$defs/paper_chunk"},
        },
        "evidence": {
            "type": "array",
            "items": {"$ref": "#/$defs/evidence"},
        },
        "hypotheses": {
            "type": "array",
            "items": {"type": "object", "additionalProperties": True},
        },
        "critique": {
            "type": "object",
            "additionalProperties": True,
        },
        "final_report": {
            "type": "object",
            "additionalProperties": True,
        },
    },
    "$defs": {
        "paper_chunk": {
            "type": "object",
            "required": ["paper_id", "page", "text"],
            "properties": {
                "paper_id": {"type": "string", "minLength": 1},
                "page": {"type": "integer", "minimum": 1},
                "text": {"type": "string"},
            },
            "additionalProperties": True,
        },
        "evidence": {
            "type": "object",
            "required": [
                "claim_id",
                "claim",
                "quote",
                "paper_id",
                "page",
                "confidence",
            ],
            "properties": {
                "claim_id": {"type": "string", "minLength": 1},
                "claim": {"type": "string", "minLength": 1},
                "quote": {"type": "string", "minLength": 1},
                "paper_id": {"type": "string", "minLength": 1},
                "page": {"type": "integer", "minimum": 1},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "additionalProperties": True,
        },
    },
}


@dataclass
class ResearchState:
    """The only shared payload that moves through the five-agent workflow."""

    question: str
    papers: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    hypotheses: list[dict[str, Any]] = field(default_factory=list)
    critique: dict[str, Any] = field(default_factory=dict)
    final_report: dict[str, Any] = field(default_factory=dict)
    # Planner output is part of the traceable state, while the six fields above
    # remain the stable public contract requested by the project.
    plan: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, *, validate: bool = True) -> dict[str, Any]:
        """Return a JSON-serializable deep copy of the state."""

        if validate:
            self.validate()
        return {
            "question": self.question,
            "plan": deepcopy(self.plan),
            "papers": deepcopy(self.papers),
            "evidence": deepcopy(self.evidence),
            "hypotheses": deepcopy(self.hypotheses),
            "critique": deepcopy(self.critique),
            "final_report": deepcopy(self.final_report),
        }

    def to_json(self, *, indent: int = 2, validate: bool = True) -> str:
        """Serialize the state without leaking provider/client objects."""

        return json.dumps(
            self.to_dict(validate=validate),
            ensure_ascii=False,
            indent=indent,
            sort_keys=True,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any], *, validate: bool = True) -> "ResearchState":
        """Construct state from a JSON-shaped mapping."""

        if not isinstance(value, Mapping):
            raise StateValidationError("ResearchState must be a JSON object")
        allowed = set(RESEARCH_STATE_SCHEMA["properties"])
        unknown = set(value) - allowed
        if unknown:
            raise StateValidationError(f"Unknown ResearchState fields: {sorted(unknown)}")
        state = cls(
            question=value.get("question", ""),
            plan=deepcopy(value.get("plan", {})),
            papers=deepcopy(value.get("papers", [])),
            evidence=deepcopy(value.get("evidence", [])),
            hypotheses=deepcopy(value.get("hypotheses", [])),
            critique=deepcopy(value.get("critique", {})),
            final_report=deepcopy(value.get("final_report", {})),
        )
        if validate:
            state.validate()
        return state

    @classmethod
    def from_json(cls, value: str, *, validate: bool = True) -> "ResearchState":
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as exc:
            raise StateValidationError("ResearchState is not valid JSON") from exc
        return cls.from_dict(decoded, validate=validate)

    def validate(self, *, require_final_report: bool = False) -> None:
        """Validate structural and citation invariants.

        The project intentionally does not require the optional ``jsonschema``
        dependency at runtime.  These checks mirror the bundled JSON Schema and
        additionally enforce cross-record citation integrity.
        """

        if not isinstance(self.question, str) or not self.question.strip():
            raise StateValidationError("question must be a non-empty string")
        if not isinstance(self.plan, dict):
            raise StateValidationError("plan must be an object")
        if not isinstance(self.papers, list):
            raise StateValidationError("papers must be an array")
        if not isinstance(self.evidence, list):
            raise StateValidationError("evidence must be an array")
        if not isinstance(self.hypotheses, list):
            raise StateValidationError("hypotheses must be an array")
        if not isinstance(self.critique, dict):
            raise StateValidationError("critique must be an object")
        if not isinstance(self.final_report, dict):
            raise StateValidationError("final_report must be an object")

        paper_ids: set[str] = set()
        for index, paper in enumerate(self.papers):
            if not isinstance(paper, Mapping):
                raise StateValidationError(f"papers[{index}] must be an object")
            paper_id = paper.get("paper_id")
            page = paper.get("page")
            text = paper.get("text")
            if not isinstance(paper_id, str) or not paper_id.strip():
                raise StateValidationError(f"papers[{index}].paper_id is required")
            if not _is_positive_page(page):
                raise StateValidationError(f"papers[{index}].page must be a positive integer")
            if not isinstance(text, str):
                raise StateValidationError(f"papers[{index}].text must be a string")
            paper_ids.add(paper_id)

        evidence_ids: set[str] = set()
        for index, evidence in enumerate(self.evidence):
            _validate_evidence(evidence, index=index, paper_ids=paper_ids)
            claim_id = evidence["claim_id"]
            if claim_id in evidence_ids:
                raise StateValidationError(f"duplicate evidence claim_id: {claim_id}")
            evidence_ids.add(claim_id)

        for index, hypothesis in enumerate(self.hypotheses):
            if not isinstance(hypothesis, Mapping):
                raise StateValidationError(f"hypotheses[{index}] must be an object")
            evidence_refs = hypothesis.get("evidence_ids", [])
            if evidence_refs is not None:
                if not isinstance(evidence_refs, list) or any(
                    not isinstance(ref, str) or ref not in evidence_ids for ref in evidence_refs
                ):
                    raise StateValidationError(
                        f"hypotheses[{index}].evidence_ids must reference known evidence"
                    )

        if self.final_report:
            _validate_final_report(
                self.final_report,
                evidence_ids=evidence_ids,
                paper_ids=paper_ids,
                require_complete=require_final_report,
            )
        elif require_final_report:
            raise StateValidationError("final_report is required")


def _is_positive_page(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _validate_evidence(
    evidence: Any,
    *,
    index: int,
    paper_ids: set[str],
) -> None:
    if not isinstance(evidence, Mapping):
        raise StateValidationError(f"evidence[{index}] must be an object")
    required = ("claim_id", "claim", "quote", "paper_id", "page", "confidence")
    missing = [field for field in required if field not in evidence]
    if missing:
        raise StateValidationError(
            f"evidence[{index}] missing required fields: {', '.join(missing)}"
        )
    for field in ("claim_id", "claim", "quote", "paper_id"):
        if not isinstance(evidence[field], str) or not evidence[field].strip():
            raise StateValidationError(f"evidence[{index}].{field} must be non-empty text")
    if evidence["paper_id"] not in paper_ids:
        raise StateValidationError(
            f"evidence[{index}].paper_id is not present in loaded papers"
        )
    if not _is_positive_page(evidence["page"]):
        raise StateValidationError(f"evidence[{index}].page must be a positive integer")
    confidence = evidence["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise StateValidationError(f"evidence[{index}].confidence must be a number")
    if not 0 <= confidence <= 1:
        raise StateValidationError(f"evidence[{index}].confidence must be between 0 and 1")


def _validate_final_report(
    report: Mapping[str, Any],
    *,
    evidence_ids: set[str],
    paper_ids: set[str],
    require_complete: bool,
) -> None:
    if not isinstance(report, Mapping):
        raise StateValidationError("final_report must be an object")
    citations = report.get("evidence", [])
    if not isinstance(citations, list):
        raise StateValidationError("final_report.evidence must be an array")
    for index, citation in enumerate(citations):
        if not isinstance(citation, Mapping):
            raise StateValidationError(f"final_report.evidence[{index}] must be an object")
        claim_id = citation.get("claim_id")
        if not isinstance(claim_id, str) or claim_id not in evidence_ids:
            raise StateValidationError(
                f"final_report.evidence[{index}] must reference a known claim_id"
            )
        if citation.get("paper_id") not in paper_ids:
            raise StateValidationError(
                f"final_report.evidence[{index}] must include a loaded paper_id"
            )
        if not _is_positive_page(citation.get("page")):
            raise StateValidationError(
                f"final_report.evidence[{index}] must include a positive page"
            )
    if require_complete:
        for field in ("title", "summary", "limitations", "next_experiment"):
            if field not in report or report[field] in (None, "", []):
                raise StateValidationError(f"final_report.{field} is required")
        if not citations:
            raise StateValidationError("final_report must contain at least one citation")


def validate_research_state(value: Mapping[str, Any] | ResearchState) -> None:
    """Validate either a state object or its JSON-shaped representation."""

    if isinstance(value, ResearchState):
        value.validate()
    else:
        ResearchState.from_dict(value, validate=True)


__all__ = [
    "RESEARCH_STATE_SCHEMA",
    "ResearchState",
    "StateValidationError",
    "validate_research_state",
]

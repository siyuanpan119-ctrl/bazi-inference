"""Audit an event interpretation without pretending to predict biography.

All interpretive links are declared, unvalidated hypotheses. This module never
turns a calendrical relationship into a medical, legal, or biographical fact.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "event-audit-1.0"
RULE_DECLARATION = {
    "用神": "定格局的十神",
    "相神": "辅佐用神形成细分格局的十神",
    "喜忌": "另列辅助或损害格局的十神",
    "扶抑": "单列，不与格局用神混名",
    "调候": "单列，不与格局用神混名",
}
FORBIDDEN_ANALYSIS_KEYS = frozenset(
    {"answer", "answer_key", "correct_answer", "ground_truth", "revealed_answer", "is_correct"}
)
EVIDENCE_KINDS = frozenset({"prompt_fact", "computed_relation", "traditional_hypothesis"})


class AuditError(ValueError):
    """The record violates the audit contract."""


def _reject_answer_fields(value: Any, location: str = "record") -> None:
    # Limit the entire input tree to exact JSON-native types. Tuple coercion
    # would otherwise change what is audited when a frozen file is reloaded.
    if type(value) is dict:
        for key, child in value.items():
            if type(key) is not str:
                raise AuditError(f"JSON object keys must be strings: {location}")
            if key in FORBIDDEN_ANALYSIS_KEYS:
                raise AuditError(f"Answer-key field forbidden before analysis: {location}.{key}")
            _reject_answer_fields(child, f"{location}.{key}")
    elif type(value) is list:
        for index, child in enumerate(value):
            _reject_answer_fields(child, f"{location}[{index}]")
    elif type(value) is float:
        if not math.isfinite(value):
            raise AuditError(f"Non-finite number is not valid JSON input: {location}")
    elif value is not None and type(value) not in {str, int, bool}:
        raise AuditError(f"Only JSON-native input types are allowed: {location}")


def _index(items: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    if type(items) is not list or any(type(item) is not dict for item in items):
        raise AuditError(f"{label} collection must be a list of JSON objects")
    indexed: dict[str, dict[str, Any]] = {}
    for item in items:
        key = item.get("id")
        if not isinstance(key, str) or not key:
            raise AuditError(f"{label} requires a nonempty string id")
        if key in indexed:
            raise AuditError(f"Duplicate {label}: {key}")
        indexed[key] = item
    return indexed


def validate_record(record: dict[str, Any]) -> None:
    """Validate declared structure, not the truth of a human interpretation.

    An answer in free text cannot reliably be detected. seen_answers is a
    mandatory provenance declaration and must be honest.
    """
    if type(record) is not dict:
        raise AuditError("Record must be a JSON object")
    _reject_answer_fields(record)
    if record.get("schema_version") != SCHEMA_VERSION:
        raise AuditError(f"schema_version must be {SCHEMA_VERSION}")
    if record.get("mode") not in {"blind", "hindsight_review"}:
        raise AuditError("mode must be blind or hindsight_review")
    if not isinstance(record.get("seen_answers"), bool):
        raise AuditError("seen_answers must be explicitly declared")
    if record["mode"] == "blind" and record["seen_answers"]:
        raise AuditError("An answer-seen record cannot be a blind prediction")
    if record.get("terminology") != RULE_DECLARATION:
        raise AuditError("Keep the user's 格局用神/相神 definitions separate from 扶抑/调候")
    if not isinstance(record.get("assumptions"), list):
        raise AuditError("Declare assumptions, including unresolved calendar choices")
    if not isinstance(record.get("question_id"), str) or not record["question_id"]:
        raise AuditError("question_id is required")
    candidates = _index(record.get("candidates", []), "candidate")
    if len(candidates) < 2:
        raise AuditError("At least two candidates are needed for comparison")
    atoms: dict[str, dict[str, Any]] = {}
    for candidate in candidates.values():
        candidate_atoms = candidate.get("atoms", [])
        if not candidate_atoms:
            raise AuditError("Each candidate must contain atomic claims")
        for atom in candidate_atoms:
            for field in ("subject", "domain", "action"):
                if not isinstance(atom.get(field), str) or not atom[field]:
                    raise AuditError(f"Each atom requires {field}")
            if "year" not in atom or "detail" not in atom:
                raise AuditError("Each atom must declare year and detail (null is allowed)")
            indexed = _index([atom], "atom")
            if atoms.keys() & indexed.keys():
                raise AuditError("Atom ids must be unique across candidates")
            atoms.update(indexed)
    evidence = _index(record.get("evidence", []), "evidence")
    for item in evidence.values():
        if item.get("kind") not in EVIDENCE_KINDS:
            raise AuditError("Unknown evidence kind")
        if item.get("direction") not in {"context", "support", "refute"}:
            raise AuditError("Unknown evidence direction")
        if not isinstance(item.get("statement"), str) or not item["statement"]:
            raise AuditError("Evidence statement is required")
        targets = item.get("target_atoms", [])
        basis = item.get("basis_ids", [])
        if not isinstance(targets, list) or not isinstance(basis, list):
            raise AuditError("target_atoms and basis_ids must be lists")
        if any(target not in atoms for target in targets):
            raise AuditError("Evidence targets an unknown atom")
        if any(parent not in evidence for parent in basis):
            raise AuditError("Hypothesis references unknown basis evidence")
        if item["kind"] == "computed_relation":
            if item["direction"] != "context" or targets:
                raise AuditError("A computed relation cannot directly determine an event")
        if item["kind"] == "traditional_hypothesis":
            if not basis or not item.get("warrant"):
                raise AuditError("A traditional hypothesis requires basis_ids and an explicit warrant")
            if item.get("validation_status") != "unvalidated":
                raise AuditError("Traditional warrants in this protocol are unvalidated")
        else:
            if basis:
                raise AuditError("Only traditional hypotheses may have derivative bases")
            if not isinstance(item.get("source_group"), str) or not item["source_group"]:
                raise AuditError("Primitive evidence requires a source_group for deduplication")
        if item["kind"] == "prompt_fact":
            if not item.get("prompt_excerpt"):
                raise AuditError("Hard facts require the original prompt excerpt")
            if item.get("source_role") != "question_stem":
                raise AuditError("A candidate option or answer key is not a hard prompt fact")
        if item["direction"] in {"support", "refute"} and not targets:
            raise AuditError("Support/refutation must name the atomic claims being compared")
    for evidence_id in evidence:
        _roots(evidence_id, evidence)
    selection = record.get("selection", {})
    if selection.get("primary") not in {*candidates, None}:
        raise AuditError("Primary choice is not a candidate")
    if selection.get("backup") not in {*candidates, None}:
        raise AuditError("Backup choice is not a candidate")
    if selection.get("primary") is not None and selection.get("primary") == selection.get("backup"):
        raise AuditError("Primary and backup must differ")
    if selection.get("status") not in {"forced_guess", "abstain", "stated_in_prompt"}:
        raise AuditError("Selection must be forced_guess, abstain, or stated_in_prompt")
    if selection["status"] == "abstain" and selection.get("primary") is not None:
        raise AuditError("An abstention cannot contain a primary choice")
    if selection["status"] != "abstain" and selection.get("primary") is None:
        raise AuditError("A submitted selection requires a primary choice")
    if not isinstance(selection.get("rationale"), str) or not selection["rationale"]:
        raise AuditError("Selection rationale is required")


def _roots(
    evidence_id: str,
    evidence: dict[str, dict[str, Any]],
    trail: frozenset[str] = frozenset(),
) -> set[str]:
    if evidence_id in trail:
        raise AuditError("Cyclic evidence dependency")
    item = evidence[evidence_id]
    if item["kind"] != "traditional_hypothesis":
        return {item["source_group"]}
    roots: set[str] = set()
    for parent in item["basis_ids"]:
        roots.update(_roots(parent, evidence, trail | {evidence_id}))
    return roots


def audit_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return coverage, counterevidence, missing evidence, and source families.

    No numeric score or probability is invented. In particular, absent evidence
    is neither negative evidence nor permission to infer an opposite biography.
    """
    validate_record(record)
    evidence = _index(record.get("evidence", []), "evidence")
    rows: list[dict[str, Any]] = []
    for candidate in record["candidates"]:
        atomic_results: list[dict[str, Any]] = []
        source_groups: set[str] = set()
        for atom in candidate["atoms"]:
            support, refute, hard_support, hard_refute = [], [], [], []
            for item in evidence.values():
                if atom["id"] not in item.get("target_atoms", []):
                    continue
                if item["direction"] == "support":
                    support.append(item["id"])
                    if item["kind"] == "prompt_fact":
                        hard_support.append(item["id"])
                    else:
                        source_groups.update(_roots(item["id"], evidence))
                elif item["direction"] == "refute":
                    refute.append(item["id"])
                    if item["kind"] == "prompt_fact":
                        hard_refute.append(item["id"])
            if hard_support and hard_refute:
                raise AuditError(f"Conflicting hard facts for atom {atom['id']}")
            atomic_results.append({
                "atom_id": atom["id"],
                "support_ids": support,
                "counterevidence_ids": refute,
                "hard_support_ids": hard_support,
                "hard_counterevidence_ids": hard_refute,
                "unresolved": not hard_support and not hard_refute,
                "missing_support": not support,
            })
        if any(row["hard_counterevidence_ids"] for row in atomic_results):
            status = "contradicted_by_prompt"
        elif all(row["hard_support_ids"] for row in atomic_results):
            status = "fully_stated_in_prompt"
        else:
            status = "unidentifiable"
        rows.append({
            "candidate_id": candidate["id"],
            "status": status,
            "atoms": atomic_results,
            "support_source_groups": sorted(source_groups),
            "distinct_source_group_count": len(source_groups),
            "source_count_is_not_probability_or_statistical_independence": True,
        })
    selected = next((row for row in rows if row["candidate_id"] == record["selection"]["primary"]), None)
    if selected is not None and selected["status"] == "contradicted_by_prompt":
        raise AuditError("Selected candidate contradicts a declared hard prompt fact")
    if record["selection"]["status"] == "stated_in_prompt":
        if selected is None or selected["status"] != "fully_stated_in_prompt":
            raise AuditError("Selected answer is not fully stated in the prompt")
    prompt_discloses_candidate = any(row["status"] == "fully_stated_in_prompt" for row in rows)
    return {
        "schema_version": SCHEMA_VERSION,
        "question_id": record["question_id"],
        "mode": record["mode"],
        "eligible_for_blind_scoring": (
            record["mode"] == "blind" and not record["seen_answers"] and not prompt_discloses_candidate
        ),
        "prompt_discloses_candidate": prompt_discloses_candidate,
        "candidate_audits": rows,
        "selection": record["selection"],
        "empirical_event_predictor": False,
    }


def _canonical(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def freeze_record(record: dict[str, Any], destination: str | Path) -> str:
    """Create a new frozen record; refuse overwrites. Hash covers all content."""
    audit = audit_record(record)
    body = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "record": record,
        "audit": audit,
    }
    digest = hashlib.sha256(_canonical(body)).hexdigest()
    envelope = {"sha256": digest, "body": body}
    with Path(destination).open("x", encoding="utf-8") as handle:
        json.dump(envelope, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
    return digest


def score_frozen(
    frozen_path: str | Path,
    revealed_choice: str,
    result_path: str | Path,
) -> dict[str, Any]:
    """Score separately after reveal. Never edits or reweights the analysis."""
    with Path(frozen_path).open(encoding="utf-8") as handle:
        envelope = json.load(handle)
    body = envelope["body"]
    if hashlib.sha256(_canonical(body)).hexdigest() != envelope["sha256"]:
        raise AuditError("Frozen record hash mismatch")
    record = body["record"]
    audit = audit_record(record)
    if audit != body["audit"]:
        raise AuditError("Stored audit differs from recomputed audit")
    if revealed_choice not in {candidate["id"] for candidate in record["candidates"]}:
        raise AuditError("Revealed choice is not a candidate")
    choice = record["selection"]["primary"]
    result = {
        "question_id": record["question_id"],
        "prediction_sha256": envelope["sha256"],
        "scored_at_utc": datetime.now(timezone.utc).isoformat(),
        "revealed_choice": revealed_choice,
        "submitted_choice": choice,
        "correct": None if choice is None else choice == revealed_choice,
        "abstained": choice is None,
        "eligible_for_blind_scoring": audit["eligible_for_blind_scoring"],
        "changes_to_interpretive_weights": None,
    }
    with Path(result_path).open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
    return result

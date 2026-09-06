"""Private, reproducible record → trial → reveal → review → promote workflow.

These helpers audit provenance and candidate-rule changes. They neither learn a
predictive model automatically nor turn an exploratory fit into validation.
The skill maintainer fills these JSON records when evaluating a proposed
release. Ordinary skill users only supply birth data and their question;
this maintainer package is not a dependency of natal or annual reports.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
from pathlib import Path

from benchmark import (create_new, digest, freeze_batch, load_json, load_registered,
                       register_receipt, score_batch, _batch_path)
from event_rules import AuditError, freeze_record


CARD_FIELDS = ("id", "title", "source_ids", "prerequisites", "structure_chain",
               "observable_claims", "alternative_explanations", "support",
               "counterexamples", "scope")


def propose_rule(request):
    """Preserve the proposed reasoning and its counterexamples; never promote."""
    if type(request) is not dict:
        raise AuditError("Rule review must be a JSON object")
    missing = [key for key in CARD_FIELDS if key not in request]
    if missing:
        raise AuditError("Missing rule-card fields: " + ", ".join(missing))
    for key in ("id", "title"):
        if not isinstance(request[key], str) or not request[key].strip():
            raise AuditError(f"{key} must be a nonempty string")
    for key in ("source_ids", "prerequisites", "structure_chain", "observable_claims",
                "alternative_explanations", "support", "counterexamples"):
        if type(request[key]) is not list:
            raise AuditError(f"{key} must be a list; an empty list means no evidence collected")
    if not request["prerequisites"] or not request["structure_chain"] or not request["observable_claims"]:
        raise AuditError("A testable rule needs prerequisites, a structure chain, and observable claims")
    if not request["alternative_explanations"]:
        raise AuditError("Declare alternative explanations to prevent one-event storytelling")
    scope = request["scope"]
    if type(scope) is not dict or not scope.get("domains"):
        raise AuditError("Rule scope needs explicitly named domains")
    if request.get("origin") not in {"hindsight_review", "traditional_source", "prospective_design"}:
        raise AuditError("Declare whether the proposal used known answers")
    card = copy.deepcopy(request)
    card.update(
        status="proposed", evidence_status="hindsight_supported" if request["origin"] == "hindsight_review" else "traditional_unvalidated",
        universally_validated=False, created_at_utc=datetime.now(timezone.utc).isoformat(),
        promotion_history=[],
    )
    return card


def validate_evaluation_plan(plan, question_persons):
    """A gate is a preregistered decision rule, not a statistical proof."""
    if type(plan) is not dict or plan.get("schema_version") != "evaluation-plan-1.0":
        raise AuditError("Declare an evaluation-plan-1.0 before freezing the trial")
    if not isinstance(plan.get("rule_id"), str) or not plan["rule_id"]:
        raise AuditError("Evaluation plan needs rule_id")
    if not isinstance(plan.get("candidate_sha256"), str) or len(plan["candidate_sha256"]) != 64:
        raise AuditError("Evaluation plan needs the proposed rule's SHA256")
    for key in ("min_new_persons", "min_questions"):
        if type(plan.get(key)) is not int or plan[key] < 1:
            raise AuditError(f"{key} must be a positive, predeclared integer")
    for key in ("min_accuracy_full", "min_coverage"):
        if type(plan.get(key)) not in {int, float} or not 0 < plan[key] <= 1:
            raise AuditError(f"{key} must be predeclared in (0, 1]")
    trained = plan.get("training_person_ids")
    if type(trained) is not list or any(not isinstance(p, str) or not p for p in trained) or len(trained) != len(set(trained)):
        raise AuditError("Declare all known training persons using stable, deduplicated IDs")
    if not isinstance(plan.get("scope"), dict) or not plan["scope"].get("domains"):
        raise AuditError("Declare the evaluated domain scope in advance")
    provenance = plan.get("person_provenance")
    if type(provenance) is not dict or set(provenance) != set(question_persons.values()):
        raise AuditError("Declare provenance for every person in the trial")
    allowed = {"new_person_no_answers_seen", "training_or_answer_seen"}
    if any(value not in allowed for value in provenance.values()):
        raise AuditError("Unknown person provenance value")
    for person in set(trained) & set(provenance):
        if provenance[person] == "new_person_no_answers_seen":
            raise AuditError("A training person cannot be relabeled as a new test person")
    if plan.get("claim") != "prospective_support_in_scope":
        raise AuditError("This gate evaluates prospective support; improvement claims need a paired baseline experiment")
    return plan


def trial(request, rules, destination, registry_dir):
    """Freeze a complete batch with all interpretation rules and optional gate."""
    plan = request.get("evaluation_plan")
    if plan is not None:
        validate_evaluation_plan(plan, request["question_persons"])
        candidates = [r for r in rules.get("rules", []) if r.get("id") == plan["rule_id"]]
        if len(candidates) != 1 or digest(candidates[0]) != plan["candidate_sha256"]:
            raise AuditError("The tested proposed rule must exactly match the frozen registry snapshot")
        if candidates[0].get("scope") != plan["scope"]:
            raise AuditError("Predeclared test scope must match the candidate rule scope")
        for record in request["records"]:
            person = request["question_persons"][record["question_id"]]
            if plan["person_provenance"][person] == "training_or_answer_seen" and record.get("mode") != "hindsight_review":
                raise AuditError("Known-person/answer-seen records must use hindsight_review")
            if plan["rule_id"] not in record.get("applied_rule_ids", []):
                raise AuditError("Every evaluation question must declare application of the tested rule")
    return freeze_batch(
        request["batch_id"], rules["version"], request["records"], request["question_persons"],
        request["expected_question_ids"], destination, registry_dir=registry_dir,
        rule_snapshot=rules, evaluation_plan=plan,
    )


def promote_rule(candidate, frozen_path, score_path, registry_dir, *, external_receipt_verified=False):
    """Promote only to experimental with narrowly scoped prospective support.

    Reject hindsight, changed gates, overlap with training persons, incomplete
    scopes and fabricated score files. The caller must inspect the external
    pre-reveal reference. No global `validated` label or automatic numeric
    reweighting is produced, even when the declared gate passes.
    """
    source = load_registered(frozen_path, registry_dir)
    body = source["body"]
    score = load_json(score_path)
    registered_score = _batch_path(registry_dir, body["batch_id"], "scores")
    if not registered_score.exists() or score != load_json(registered_score):
        raise AuditError("Use the score registered for this exact batch")
    if score.get("prediction_sha256") != source["sha256"]:
        raise AuditError("Score is for another trial")
    plan = validate_evaluation_plan(body.get("evaluation_plan"), body["question_persons"])
    if candidate.get("status") != "proposed" or plan["rule_id"] != candidate.get("id"):
        raise AuditError("Only the proposed rule named before reveal can be promoted")
    if plan["candidate_sha256"] != digest(candidate) or candidate.get("scope") != plan["scope"]:
        raise AuditError("Candidate changed after trial declaration")
    if any(plan["rule_id"] not in record.get("applied_rule_ids", []) for record in body["records"]):
        raise AuditError("The frozen questions do not declare application of the tested rule")
    if not score.get("external_precommit_receipt") or not external_receipt_verified:
        raise AuditError("An externally checked pre-reveal submission is required; a local hash alone is insufficient")
    people = set(body["question_persons"].values())
    if people & set(plan["training_person_ids"]):
        raise AuditError("The promotion trial reuses training persons")
    if any(plan["person_provenance"][p] != "new_person_no_answers_seen" for p in people):
        raise AuditError("Only genuinely new persons with unseen answers qualify")
    if score["excluded_question_count"] or any(not row["eligible"] for row in score["rows"]):
        raise AuditError("Hindsight or disclosed-answer questions cannot support promotion")
    metrics = score["eligible_score"]
    failures = []
    if len(people) < plan["min_new_persons"]:
        failures.append("too few new persons")
    if metrics["questions"] < plan["min_questions"]:
        failures.append("too few questions")
    if metrics["accuracy_on_full_denominator"] is None or metrics["accuracy_on_full_denominator"] < plan["min_accuracy_full"]:
        failures.append("full-denominator accuracy below declared gate")
    if metrics["coverage"] is None or metrics["coverage"] < plan["min_coverage"]:
        failures.append("coverage below declared gate")
    if failures:
        raise AuditError("Promotion gate failed: " + "; ".join(failures))
    promoted = copy.deepcopy(candidate)
    promoted.update(status="experimental", evidence_status="prospective_trial_supported", universally_validated=False)
    promoted["promotion_history"] = list(candidate.get("promotion_history", [])) + [{
        "trial_sha256": source["sha256"], "score_sha256": digest(score),
        "evaluation_plan": plan, "metrics": metrics, "persons": len(people),
        "promoted_at_utc": datetime.now(timezone.utc).isoformat(),
        "external_reference_checked_by_caller": True,
        "scope_limit": "Supports this declared trial and scope; does not establish causality, universal validity or accuracy improvement over another version.",
    }]
    return promoted


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("record", "review"):
        p = sub.add_parser(command)
        p.add_argument("--input", required=True)
        p.add_argument("--out", required=True)
    p = sub.add_parser("trial")
    p.add_argument("--input", required=True)
    p.add_argument("--rules", required=True)
    p.add_argument("--registry", required=True)
    p.add_argument("--out", required=True)
    p = sub.add_parser("receipt")
    p.add_argument("--registry", required=True)
    p.add_argument("--batch-id", required=True)
    p.add_argument("--reference", required=True)
    p = sub.add_parser("reveal")
    p.add_argument("--frozen", required=True)
    p.add_argument("--answers", required=True)
    p.add_argument("--registry", required=True)
    p.add_argument("--out", required=True)
    p = sub.add_parser("promote")
    p.add_argument("--candidate", required=True)
    p.add_argument("--frozen", required=True)
    p.add_argument("--score", required=True)
    p.add_argument("--registry", required=True)
    p.add_argument("--external-receipt-verified", action="store_true")
    p.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.command == "record":
        print(freeze_record(load_json(args.input), args.out))
    elif args.command == "trial":
        print(trial(load_json(args.input), load_json(args.rules), args.out, args.registry))
    elif args.command == "receipt":
        print(register_receipt(args.registry, args.batch_id, args.reference)["prediction_sha256"])
    elif args.command == "reveal":
        result = score_batch(args.frozen, load_json(args.answers), args.out, registry_dir=args.registry)
        print(result["eligible_score"])
    elif args.command == "review":
        result = propose_rule(load_json(args.input))
        create_new(args.out, result)
        print(digest(result))
    else:
        result = promote_rule(load_json(args.candidate), args.frozen, args.score, args.registry,
                              external_receipt_verified=args.external_receipt_verified)
        create_new(args.out, result)
        print(digest(result))


if __name__ == "__main__":
    main()

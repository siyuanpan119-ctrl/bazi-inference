"""Describe paired old/new submissions without declaring statistical improvement."""
from __future__ import annotations

import argparse
from collections import defaultdict

from benchmark import (load_json, load_registered, create_new, summarize, _batch_path)
from event_rules import AuditError


def _registered_score(path, source, registry_dir):
    score = load_json(path)
    registered = _batch_path(registry_dir, source["body"]["batch_id"], "scores")
    if not registered.exists() or score != load_json(registered):
        raise AuditError("Comparison requires each batch's registered score")
    if score.get("prediction_sha256") != source["sha256"]:
        raise AuditError("Score belongs to a different frozen submission")
    return score


def compare_versions(old_frozen, old_score, new_frozen, new_score, registry_dir,
                     *, external_receipts_checked=False):
    """Compare exact question/person/candidate/key sets, retaining abstentions.

    Prospective design is a provenance declaration, not independently certified.
    Without matching predeclared experiment IDs this remains descriptive even
    if all predictions are correct. Caller checks actual external commitments.
    """
    old_source = load_registered(old_frozen, registry_dir)
    new_source = load_registered(new_frozen, registry_dir)
    old, new = old_source["body"], new_source["body"]
    if old_source["sha256"] == new_source["sha256"] or old["batch_id"] == new["batch_id"]:
        raise AuditError("Compare two distinct registered submissions")
    old_sc = _registered_score(old_score, old_source, registry_dir)
    new_sc = _registered_score(new_score, new_source, registry_dir)
    old_records = {r["question_id"]: r for r in old["records"]}
    new_records = {r["question_id"]: r for r in new["records"]}
    if set(old_records) != set(new_records):
        raise AuditError("Versions must answer the same complete question set")
    if old["question_persons"] != new["question_persons"]:
        raise AuditError("Versions must use identical stable person mappings")
    old_rows = {r["question_id"]: r for r in old_sc["rows"]}
    new_rows = {r["question_id"]: r for r in new_sc["rows"]}
    if set(old_rows) != set(old_records) or set(new_rows) != set(old_records):
        raise AuditError("Score rows must cover the full frozen question set")
    paired = []
    for qid in sorted(old_records):
        old_options = {c["id"]: c for c in old_records[qid]["candidates"]}
        new_options = {c["id"]: c for c in new_records[qid]["candidates"]}
        if old_options != new_options:
            raise AuditError(f"Candidate meanings or options differ for {qid}")
        a, b = old_rows[qid], new_rows[qid]
        for field in ("revealed_choice", "option_count", "eligible", "person_id"):
            if a[field] != b[field]:
                raise AuditError(f"Paired {field} differs for {qid}")
        a_hit, b_hit = a["correct"] is True, b["correct"] is True
        paired.append({"question_id": qid, "person_id": a["person_id"],
                       "eligible": a["eligible"], "old_correct": a_hit,
                       "new_correct": b_hit, "correctness_delta": int(b_hit)-int(a_hit),
                       "old_submitted_choice": a["submitted_choice"],
                       "new_submitted_choice": b["submitted_choice"]})
    eligible = [r for r in paired if r["eligible"]]
    included_ids = {r["question_id"] for r in eligible}
    old_metrics = summarize([old_rows[q] for q in sorted(included_ids)])
    new_metrics = summarize([new_rows[q] for q in sorted(included_ids)])
    old_all, new_all = summarize(list(old_rows.values())), summarize(list(new_rows.values()))
    people = defaultdict(list)
    for row in paired:
        people[row["person_id"]].append(row)
    per_person = {}
    for person, rows in sorted(people.items()):
        ids = [r["question_id"] for r in rows if r["eligible"]]
        before, after = summarize([old_rows[q] for q in ids]), summarize([new_rows[q] for q in ids])
        per_person[person] = {"old": before, "new": after,
                              "correctness_delta": sum(r["correctness_delta"] for r in rows if r["eligible"])}
    reasons = []
    old_plan, new_plan = old.get("evaluation_plan") or {}, new.get("evaluation_plan") or {}
    experiment_id = old_plan.get("experiment_id")
    if not isinstance(experiment_id, str) or not experiment_id or experiment_id != new_plan.get("experiment_id"):
        reasons.append("No matching experiment_id was frozen in both evaluation plans")
        experiment_id = None
    all_people = set(old["question_persons"].values())
    for label, plan in (("old", old_plan), ("new", new_plan)):
        provenance = plan.get("person_provenance", {})
        if set(provenance) != all_people or any(v != "new_person_no_answers_seen" for v in provenance.values()):
            reasons.append(f"{label} version lacks complete new-person declarations")
        trained = plan.get("training_person_ids")
        if type(trained) is not list or set(trained) & all_people:
            reasons.append(f"{label} version lacks a clean training-person exclusion")
    if len(eligible) != len(paired):
        reasons.append("Hindsight or disclosed-answer questions are present")
    have_receipts = bool(old_sc.get("external_precommit_receipt") and new_sc.get("external_precommit_receipt"))
    checked = bool(external_receipts_checked and have_receipts)
    if not checked:
        reasons.append("Both actual external pre-reveal submissions have not been checked")
    delta = (new_metrics["accuracy_on_full_denominator"] - old_metrics["accuracy_on_full_denominator"]
             if eligible else None)
    return {
        "schema_version": "paired-version-comparison-1.0",
        "mode": "prospective_design_declared" if not reasons else "nonprospective_descriptive",
        "experiment_id": experiment_id,
        "old_rule_version": old["rule_version"], "new_rule_version": new["rule_version"],
        "old_rule_sha256": old["rule_sha256"], "new_rule_sha256": new["rule_sha256"],
        "old_prediction_sha256": old_source["sha256"], "new_prediction_sha256": new_source["sha256"],
        "comparison_has_external_receipts_checked": checked,
        "nonprospective_reasons": reasons,
        "total_questions": len(paired), "eligible_questions": len(eligible),
        "excluded_questions": len(paired)-len(eligible),
        "old": old_metrics, "new": new_metrics,
        "full_denominator_accuracy_delta": delta,
        "coverage_delta": new_metrics["coverage"]-old_metrics["coverage"] if eligible else None,
        "n01_old_not_correct_new_correct": sum(not r["old_correct"] and r["new_correct"] for r in eligible),
        "n10_old_correct_new_not_correct": sum(r["old_correct"] and not r["new_correct"] for r in eligible),
        "descriptive_all_rows_including_hindsight": {"old": old_all, "new": new_all,
             "full_denominator_accuracy_delta": new_all["accuracy_on_full_denominator"]-old_all["accuracy_on_full_denominator"]},
        "by_person": per_person, "rows": paired,
        "statistical_significance_assessed": False, "accuracy_improvement_established": False,
        "limitations": ["External chronology and unseen-answer declarations require human/source verification.",
                        "A positive paired difference describes these submissions, not proven general improvement.",
                        "Same-person questions are dependent; n01/n10 are descriptive counts only.",
                        "Hindsight rows are shown separately and cannot support a prospective improvement claim."],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("old-frozen", "old-score", "new-frozen", "new-score", "registry", "out"):
        parser.add_argument("--"+key, required=True)
    parser.add_argument("--external-receipts-checked", action="store_true")
    args = parser.parse_args()
    result = compare_versions(args.old_frozen, args.old_score, args.new_frozen, args.new_score,
                              args.registry, external_receipts_checked=args.external_receipts_checked)
    create_new(args.out, result)
    print(result["mode"], "delta=", result["full_denominator_accuracy_delta"])


if __name__ == "__main__":
    main()

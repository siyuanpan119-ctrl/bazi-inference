"""Freeze and score one registered complete submission per batch.

The local registry prevents accidental version shopping across output paths.
It is not a trusted timestamp: publish the submission hash externally before
answers are shown, and keep the registry private and persistent between runs.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile

from event_rules import AuditError, audit_record, _reject_answer_fields


SCHEMA_VERSION = "batch-benchmark-2.0"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def envelope(body):
    return {"sha256": digest(body), "body": body}


def create_new(path, value):
    """Publish a fully written JSON file atomically; never replace a file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                     allow_nan=False) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def load_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise AuditError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique)


def _batch_path(registry_dir, batch_id, kind="submissions"):
    if not isinstance(batch_id, str) or not batch_id.strip():
        raise AuditError("batch_id must be a nonempty string")
    token = hashlib.sha256(batch_id.encode("utf-8")).hexdigest()
    return Path(registry_dir) / kind / (token + ".json")


def _check_envelope(value):
    if type(value) is not dict or set(value) != {"body", "sha256"}:
        raise AuditError("Invalid frozen envelope")
    if digest(value["body"]) != value["sha256"]:
        raise AuditError("Batch hash mismatch")
    return value["body"]


def _validate_set(records, question_persons, expected_question_ids):
    if type(records) is not list or not records or any(type(r) is not dict for r in records):
        raise AuditError("records must be a nonempty list of objects")
    ids = [r.get("question_id") for r in records]
    if any(not isinstance(q, str) or not q for q in ids):
        raise AuditError("Every question needs a string question_id")
    if type(expected_question_ids) is not list or any(not isinstance(q, str) or not q for q in expected_question_ids):
        raise AuditError("expected_question_ids must be a list of string ids")
    if len(ids) != len(set(ids)) or len(expected_question_ids) != len(set(expected_question_ids)):
        raise AuditError("Duplicate question id")
    if type(question_persons) is not dict or set(ids) != set(expected_question_ids) or set(ids) != set(question_persons):
        raise AuditError("Submission must include every declared question and person mapping")
    if any(not isinstance(v, str) or not v for v in question_persons.values()):
        raise AuditError("Stable nonempty person_ids are required")


def validate_person_split(question_persons, question_partitions):
    """Reject question-level train/test splits that leak a person's biography."""
    if set(question_persons) != set(question_partitions):
        raise AuditError("Declare one partition per question")
    by_person = defaultdict(set)
    for qid, person in question_persons.items():
        partition = question_partitions[qid]
        if partition not in {"training", "validation", "test"}:
            raise AuditError("partition must be training, validation, or test")
        by_person[person].add(partition)
    if any(len(values) != 1 for values in by_person.values()):
        raise AuditError("All questions for one person must stay in one partition")
    return {person: next(iter(parts)) for person, parts in by_person.items()}


def freeze_batch(batch_id, rule_version, records, question_cases,
                 expected_question_ids, destination, *, registry_dir,
                 rule_snapshot, evaluation_plan=None):
    """Register first, then export. question_cases values are stable person IDs.

    A registry failure never falls back to an unregistered snapshot. If exporting
    fails after registration, recover the registered submission without rerunning
    the prediction. Different registry roots are not independent experiments.
    """
    if not isinstance(rule_version, str) or not rule_version:
        raise AuditError("Declare rule_version")
    if type(rule_snapshot) is not dict or rule_snapshot.get("version") != rule_version:
        raise AuditError("Freeze the complete matching rule snapshot")
    _reject_answer_fields(rule_snapshot)
    _validate_set(records, question_cases, expected_question_ids)
    _reject_answer_fields(records)
    if evaluation_plan is not None:
        _reject_answer_fields(evaluation_plan)
    audits = [audit_record(record) for record in records]
    if Path(destination).exists():
        raise FileExistsError(destination)
    body = {
        "schema_version": SCHEMA_VERSION, "batch_id": batch_id,
        "rule_version": rule_version, "rule_sha256": digest(rule_snapshot),
        "rule_snapshot": rule_snapshot, "evaluation_plan": evaluation_plan,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "expected_question_ids": expected_question_ids,
        "question_persons": question_cases, "records": records, "audits": audits,
        "external_precommit_required": True,
    }
    result = envelope(body)
    registration = _batch_path(registry_dir, batch_id)
    try:
        create_new(registration, result)
    except FileExistsError as error:
        raise AuditError("Batch already registered; reuse its first submission, do not select another version") from error
    if Path(destination).resolve() != registration.resolve():
        create_new(destination, result)
    return result["sha256"]


def load_registered(frozen_path, registry_dir):
    source = load_json(frozen_path)
    body = _check_envelope(source)
    if body.get("schema_version") != SCHEMA_VERSION:
        raise AuditError("Unsupported batch schema")
    registration = _batch_path(registry_dir, body["batch_id"])
    if not registration.exists() or load_json(registration) != source:
        raise AuditError("Submission does not match its first local registration")
    if body["rule_sha256"] != digest(body["rule_snapshot"]):
        raise AuditError("Rule snapshot hash mismatch")
    if body["rule_snapshot"].get("version") != body["rule_version"]:
        raise AuditError("Rule snapshot version mismatch")
    _validate_set(body["records"], body["question_persons"], body["expected_question_ids"])
    audits = [audit_record(record) for record in body["records"]]
    if audits != body["audits"]:
        raise AuditError("Frozen audits disagree with recomputation")
    return source


def register_receipt(registry_dir, batch_id, external_reference):
    """Record where the hash was actually sent before revealing answers.

    The program cannot verify external content, honesty, or independent time.
    A reviewer must inspect the referenced message/commit/repository history.
    """
    registration = _batch_path(registry_dir, batch_id)
    source = load_json(registration)
    _check_envelope(source)
    if _batch_path(registry_dir, batch_id, "scores").exists():
        raise AuditError("Cannot add a pre-reveal receipt after scoring")
    if not isinstance(external_reference, str) or not external_reference.strip():
        raise AuditError("Reference the actual external hash submission")
    receipt = {
        "batch_id": batch_id, "prediction_sha256": source["sha256"],
        "external_reference": external_reference,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "external_reference_verified_by_program": False,
    }
    create_new(_batch_path(registry_dir, batch_id, "receipts"), receipt)
    return receipt


def summarize(rows):
    n = len(rows)
    answered = sum(row["submitted_choice"] is not None for row in rows)
    correct = sum(row["correct"] is True for row in rows)
    return {
        "questions": n, "answered": answered, "abstained": n - answered,
        "correct": correct, "coverage": answered / n if n else None,
        "accuracy_on_full_denominator": correct / n if n else None,
        "accuracy_among_answered": correct / answered if answered else None,
        "uniform_random_expected_correct_if_all_answered": sum(1 / row["option_count"] for row in rows),
    }


def score_batch(frozen_path, revealed_keys, result_path, *, registry_dir):
    source = load_registered(frozen_path, registry_dir)
    body = source["body"]
    ids = body["expected_question_ids"]
    if type(revealed_keys) is not dict or set(revealed_keys) != set(ids):
        raise AuditError("Exactly one revealed answer for every frozen question is required")
    rows = []
    for record, audit in zip(body["records"], body["audits"]):
        qid = record["question_id"]
        key = revealed_keys[qid]
        choices = {candidate["id"] for candidate in record["candidates"]}
        if not isinstance(key, str) or key not in choices:
            raise AuditError(f"Invalid revealed key for {qid}")
        pick = record["selection"]["primary"]
        rows.append({
            "question_id": qid, "person_id": body["question_persons"][qid],
            "submitted_choice": pick, "revealed_choice": key,
            "option_count": len(choices), "correct": None if pick is None else pick == key,
            "eligible": audit["eligible_for_blind_scoring"],
        })
    eligible = [row for row in rows if row["eligible"]]
    people = defaultdict(list)
    for row in eligible:
        people[row["person_id"]].append(row)
    receipt_path = _batch_path(registry_dir, body["batch_id"], "receipts")
    receipt = load_json(receipt_path) if receipt_path.exists() else None
    if receipt and receipt["prediction_sha256"] != source["sha256"]:
        raise AuditError("Receipt hash mismatch")
    result = {
        "schema_version": SCHEMA_VERSION, "batch_id": body["batch_id"],
        "rule_version": body["rule_version"], "rule_sha256": body["rule_sha256"],
        "prediction_sha256": source["sha256"], "answer_keys_sha256": digest(revealed_keys),
        "scored_at_utc": datetime.now(timezone.utc).isoformat(),
        "declared_question_count": len(rows), "excluded_question_count": len(rows) - len(eligible),
        "eligible_score": summarize(eligible),
        "by_person": {person: summarize(group) for person, group in sorted(people.items())},
        "rows": rows, "external_precommit_receipt": receipt,
        "independent_blind_provenance_certified": False,
        "limitations": [
            "The local registry prevents duplicate batch submissions only within this retained registry.",
            "Send the hash externally before reveal; local timestamps and receipts cannot certify unseen answers.",
            "Questions for one person are dependent; split and compare by person, not random questions.",
            "Abstentions remain in the full eligible denominator; report both coverage and selective accuracy.",
            "A new quiz may differ in difficulty; raw historical accuracy is not a matched control.",
        ],
    }
    if Path(result_path).exists():
        raise FileExistsError(result_path)
    registration = _batch_path(registry_dir, body["batch_id"], "scores")
    try:
        create_new(registration, result)
    except FileExistsError as error:
        raise AuditError("Batch already scored; use its registered score") from error
    if Path(result_path).resolve() != registration.resolve():
        create_new(result_path, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    freeze = sub.add_parser("freeze")
    freeze.add_argument("--input", required=True)
    freeze.add_argument("--rules", required=True)
    freeze.add_argument("--registry", required=True)
    freeze.add_argument("--out", required=True)
    score = sub.add_parser("score")
    score.add_argument("--frozen", required=True)
    score.add_argument("--answers", required=True)
    score.add_argument("--registry", required=True)
    score.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.command == "freeze":
        request, rules = load_json(args.input), load_json(args.rules)
        value = freeze_batch(request["batch_id"], rules["version"], request["records"],
                             request["question_persons"], request["expected_question_ids"],
                             args.out, registry_dir=args.registry, rule_snapshot=rules,
                             evaluation_plan=request.get("evaluation_plan"))
        print(json.dumps({"sha256": value}, ensure_ascii=False))
    else:
        value = score_batch(args.frozen, load_json(args.answers), args.out, registry_dir=args.registry)
        print(json.dumps(value["eligible_score"], ensure_ascii=False))


if __name__ == "__main__":
    main()

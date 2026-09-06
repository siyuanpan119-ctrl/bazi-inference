"""Four-arm maintainer controls built on existing freeze/hash/score primitives.

Only synthetic regression tests ship publicly. Build and submit never read keys;
score reads keys only after every predeclared arm/condition/repetition is frozen.
Local registries cannot certify truthful declarations or external timestamps.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
import random
import statistics

from benchmark import (AuditError, _batch_path, _check_envelope, canonical,
                       create_new, digest, envelope, load_json, summarize,
                       validate_person_split)
from event_rules import _reject_answer_fields
from trial_preflight import MODEL_FIELDS, UNKNOWN, resolve_artifact, skill_manifest

SCHEMA = "controlled-trial-1.0"
ARMS = ("stem_only", "bazi", "ziwei", "fusion")
CONDITIONS = ("original", "shuffled_charts", "shuffled_options")
PROVENANCE = {"known_development", "unseen_declared", "synthetic"}
KEY_FIELDS = {"answers", "answer_keys", "correct_choice", "revealed_choice"}
POLICY = {"all_repetitions": True, "retain_all_questions": True,
          "primary_only": True, "report_coverage": True}


def reject_key_payload(value):
    _reject_answer_fields(value)
    if isinstance(value, dict):
        if set(value) & KEY_FIELDS:
            raise AuditError("Answer payloads must stay in a separate curator-only file")
        for child in value.values():
            reject_key_payload(child)
    elif isinstance(value, list):
        for child in value:
            reject_key_payload(child)


def validate_spec(spec):
    reject_key_payload(spec)
    if spec.get("schema_version") != SCHEMA:
        raise AuditError("Use controlled-trial-1.0")
    if not isinstance(spec.get("trial_id"), str) or not spec["trial_id"].strip():
        raise AuditError("Declare trial_id")
    if spec.get("scoring_policy") != POLICY:
        raise AuditError("Keep all questions, primary choices, and every registered repetition")
    if type(spec.get("repetitions")) is not int or not 1 <= spec["repetitions"] <= 100:
        raise AuditError("Predeclare repetitions between 1 and 100")
    if type(spec.get("seed")) is not int:
        raise AuditError("Predeclare an integer shuffle seed")
    if spec.get("context_policy") != "isolated_no_keys_no_other_arms":
        raise AuditError("Each run needs isolated context without keys or other arm outputs")
    host = spec.get("host", {})
    if not isinstance(host, dict) or any(not isinstance(host.get(k), str)
            or host[k].strip().lower() in UNKNOWN for k in MODEL_FIELDS):
        raise AuditError("Freeze actual host model/version/reasoning/instruction settings; unknown is not comparable")
    if type(host.get("max_output_tokens")) is not int or host["max_output_tokens"] <= 0:
        raise AuditError("Freeze a shared positive output token budget")
    if "sampling" not in host or not isinstance(host["sampling"], dict) or not host["sampling"]:
        raise AuditError("Freeze sampling settings, including provider defaults if not controllable")
    questions = spec.get("questions")
    if not isinstance(questions, list) or not questions:
        raise AuditError("Supply nonempty questions without answer fields")
    people, partitions, qids = {}, {}, set()
    for q in questions:
        if not isinstance(q, dict) or not isinstance(q.get("id"), str) or not q["id"]:
            raise AuditError("Every question needs a stable id")
        if q["id"] in qids:
            raise AuditError("Duplicate question id")
        qids.add(q["id"])
        if not isinstance(q.get("person_id"), str) or not q["person_id"]:
            raise AuditError("Every question needs a stable person id")
        people[q["id"]] = q["person_id"]
        partitions[q["id"]] = q.get("partition")
        if not isinstance(q.get("stem"), str) or not q["stem"].strip():
            raise AuditError("Supply the actual question stem")
        if q.get("stem_has_no_birth_or_chart") is not True:
            raise AuditError("Curator must remove birth/chart/identifying metadata from baseline stems")
        options = q.get("options")
        if (not isinstance(options, dict) or not 2 <= len(options) <= 26
                or any(not isinstance(k, str) or not k or not isinstance(v, str) or not v.strip()
                       for k, v in options.items())):
            raise AuditError("Options map stable semantic ids to actual text (2..26 choices)")
    person_partitions = validate_person_split(people, partitions)
    provenance = spec.get("person_provenance", {})
    if set(provenance) != set(people.values()) or any(v not in PROVENANCE for v in provenance.values()):
        raise AuditError("Declare known_development, unseen_declared, or synthetic for every person")
    for person, partition in person_partitions.items():
        if provenance[person] == "known_development" and partition != "training":
            raise AuditError("Known answers/persons must remain training/development, never holdout")
    historical = spec.get("known_development_person_ids")
    if (not isinstance(historical, list) or any(not isinstance(p, str) or not p for p in historical)
            or len(set(historical)) != len(historical)):
        raise AuditError("Declare stable known development person ids, including previous batches")
    for person in set(historical) & set(people.values()):
        if provenance[person] != "known_development" or person_partitions[person] != "training":
            raise AuditError("Previously known development person cannot be relabeled as unseen")
    charts = spec.get("charts", {})
    if set(charts) != set(people.values()):
        raise AuditError("Supply one chart pair for every person")
    for pair in charts.values():
        if not isinstance(pair, dict) or set(pair) != {"bazi", "ziwei"}:
            raise AuditError("Every chart pair must have separate bazi and ziwei payloads")
        if any(not isinstance(pair[k], dict) or not pair[k] for k in ("bazi", "ziwei")):
            raise AuditError("Four-arm comparison requires computed nonempty charts in both systems")
    return people, person_partitions


def rotated_order(values, rng):
    """A randomized cycle guarantees no self-map while preserving all items."""
    order = list(values)
    rng.shuffle(order)
    if len(order) < 2:
        raise AuditError("Shuffle controls need at least two people per partition")
    return dict(zip(order, order[1:] + order[:1]))


def make_views(spec):
    people, partitions = validate_spec(spec)
    views, mappings = {}, {}
    for repetition in range(1, spec["repetitions"] + 1):
        rng = random.Random(spec["seed"] + repetition)
        donors = {}
        for partition in sorted(set(partitions.values())):
            group = sorted(p for p, part in partitions.items() if part == partition)
            donors.update(rotated_order(group, rng))
        option_orders = {}
        for q in spec["questions"]:
            option_orders[q["id"]] = rotated_order(list(q["options"]), rng)
        for condition in CONDITIONS:
            for arm in ARMS:
                run_id = f"r{repetition:03d}/{condition}/{arm}"
                questions, maps, donor_map = [], {}, {}
                for q in spec["questions"]:
                    qid, person = q["id"], q["person_id"]
                    semantic_ids = list(q["options"])
                    if condition == "shuffled_options":
                        semantic_ids = [option_orders[qid][x] for x in semantic_ids]
                    display_map = {chr(65 + i): item for i, item in enumerate(semantic_ids)}
                    current = {"id": qid, "stem": q["stem"],
                               "options": {label: q["options"][item] for label, item in display_map.items()}}
                    donor = donors[person] if condition == "shuffled_charts" else person
                    if arm != "stem_only":
                        systems = ("bazi", "ziwei") if arm == "fusion" else (arm,)
                        current["charts"] = {s: spec["charts"][donor][s] for s in systems}
                    questions.append(current)
                    maps[qid] = display_map
                    donor_map[person] = donor
                views[run_id] = {"schema_version": SCHEMA,
                    "view_id": digest({"trial": spec["trial_id"], "run": run_id})[:20],
                    "method": arm, "host": spec["host"],
                    "instruction": ("Use only the supplied stem/options; do not derive or retrieve a chart."
                        if arm == "stem_only" else "Use only the supplied method payloads and frozen instructions; return a primary choice or null."),
                    "questions": questions}
                mappings[run_id] = {"repetition": repetition, "condition": condition,
                                   "arm": arm, "display_to_semantic": maps, "chart_donors": donor_map}
    return views, mappings


def prepare(spec, root, destination, registry):
    """Freeze experiment and construct views. No answer input is accepted here."""
    root, destination = Path(root).resolve(), Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    views, mappings = make_views(spec)
    skill_root = resolve_artifact(root, spec["skill_root"])
    fusion = resolve_artifact(root, spec["fusion_policy_file"])
    fusion_text = fusion.read_text(encoding="utf-8")
    if not fusion_text.strip():
        raise AuditError("Freeze an explicit fusion policy before running any arm")
    body = {"schema_version": SCHEMA, "spec": spec, "views": views, "mappings": mappings,
            "skill_snapshot": skill_manifest(skill_root), "fusion_policy": fusion_text,
            "artifact_root": str(root), "bundle_root": str(destination.resolve()),
            "external_timestamp_verified": False, "prediction_accuracy_validated": False}
    frozen = envelope(body)
    path = _batch_path(registry, spec["trial_id"], "controlled-plans")
    try:
        create_new(path, frozen)
    except FileExistsError as error:
        raise AuditError("Trial already registered; recover its first plan instead of changing seeds/settings") from error
    create_new(destination / "manifest.json", frozen)
    for run_id, view in views.items():
        create_new(destination / "views" / (view["view_id"] + ".json"), view)
    return {"trial_sha256": frozen["sha256"], "runs": len(views),
            "questions": len(spec["questions"]), "persons": len(spec["person_provenance"]),
            "prediction_accuracy_validated": False}


def registered_plan(manifest_path, registry):
    manifest = load_json(manifest_path)
    body = _check_envelope(manifest)
    if body.get("schema_version") != SCHEMA:
        raise AuditError("Unsupported controlled trial schema")
    path = _batch_path(registry, body["spec"]["trial_id"], "controlled-plans")
    if not path.exists() or load_json(path) != manifest:
        raise AuditError("Plan differs from first registered plan")
    return manifest


def submit(manifest_path, run_id, submission, registry):
    """Freeze first complete submission for one run; keys remain unavailable."""
    source = registered_plan(manifest_path, registry)
    body = source["body"]
    if run_id not in body["views"]:
        raise AuditError("Run not predeclared")
    reject_key_payload(submission)
    artifact_root = Path(body["artifact_root"])
    live_skill = skill_manifest(resolve_artifact(artifact_root, body["spec"]["skill_root"]))
    live_fusion = resolve_artifact(artifact_root, body["spec"]["fusion_policy_file"]).read_text(encoding="utf-8")
    if live_skill != body["skill_snapshot"] or live_fusion != body["fusion_policy"]:
        raise AuditError("Actual skill or fusion policy changed after registration")
    view_path = Path(body["bundle_root"]) / "views" / (body["views"][run_id]["view_id"] + ".json")
    if load_json(view_path) != body["views"][run_id]:
        raise AuditError("Actual visible prompt changed after registration")
    if submission.get("view_sha256") != digest(body["views"][run_id]):
        raise AuditError("Submission must identify its exact visible prompt")
    if submission.get("host") != body["spec"]["host"]:
        raise AuditError("Actual declared host differs from frozen shared host")
    if submission.get("skill_sha256") != body["skill_snapshot"]["sha256"]:
        raise AuditError("Submission must identify the frozen skill snapshot")
    records = submission.get("records")
    if not isinstance(records, list) or any(not isinstance(r, dict) for r in records):
        raise AuditError("Supply all records, including null primary choices")
    ids = [r.get("question_id") for r in records]
    expected = body["mappings"][run_id]["display_to_semantic"]
    if len(ids) != len(set(ids)) or set(ids) != set(expected):
        raise AuditError("Every run must include exactly the full question set")
    for r in records:
        if "primary" not in r or (r["primary"] is not None and r["primary"] not in expected[r["question_id"]]):
            raise AuditError("Primary must be a displayed option label or null")
        if not isinstance(r.get("rationale"), str) or not r["rationale"].strip():
            raise AuditError("Retain actual rationale, including inability to distinguish")
    result = envelope({"trial_sha256": source["sha256"], "run_id": run_id, "submission": submission})
    key = body["spec"]["trial_id"] + ":" + run_id
    path = _batch_path(registry, key, "controlled-submissions")
    try:
        create_new(path, result)
    except FileExistsError as error:
        raise AuditError("Run already submitted; retain the first result and all declared repetitions") from error
    return result["sha256"]


def all_submissions(source, registry):
    body, results = source["body"], {}
    for run_id in body["views"]:
        key = body["spec"]["trial_id"] + ":" + run_id
        path = _batch_path(registry, key, "controlled-submissions")
        if not path.exists():
            raise AuditError("Freeze all predeclared runs before reveal; missing " + run_id)
        row = _check_envelope(load_json(path))
        if row.get("trial_sha256") != source["sha256"] or row.get("run_id") != run_id:
            raise AuditError("Submission identity differs from frozen plan")
        results[run_id] = row["submission"]["records"]
    return results


def grouped_metrics(rows):
    by_person = defaultdict(list)
    for row in rows:
        by_person[row["person_id"]].append(row)
    per_person = {p: summarize(group) for p, group in sorted(by_person.items())}
    return {**summarize(rows), "persons": len(per_person), "by_person": per_person,
            "person_macro_accuracy": (statistics.mean(x["accuracy_on_full_denominator"] for x in per_person.values())
                                      if per_person else None)}


def transitions(before, after, *, include_people=True):
    a, b = {r["question_id"]: r for r in before}, {r["question_id"]: r for r in after}
    improved = sum(a[q]["correct"] is not True and b[q]["correct"] is True for q in a)
    worsened = sum(a[q]["correct"] is True and b[q]["correct"] is not True for q in a)
    result = {"changed_to_correct": improved, "changed_from_correct": worsened,
              "net_correct_change": improved - worsened,
              "semantic_choice_changes": sum(a[q]["submitted_choice"] != b[q]["submitted_choice"] for q in a)}
    if include_people:
        result["by_person"] = {person: transitions(
            [r for r in before if r["person_id"] == person],
            [r for r in after if r["person_id"] == person], include_people=False)
            for person in sorted({r["person_id"] for r in before})}
    return result


def score(manifest_path, answers_path, registry, destination):
    source = registered_plan(manifest_path, registry)
    submissions = all_submissions(source, registry)  # Intentionally before reading keys.
    body, spec = source["body"], source["body"]["spec"]
    answers = load_json(answers_path)
    questions = {q["id"]: q for q in spec["questions"]}
    if not isinstance(answers, dict) or set(answers) != set(questions):
        raise AuditError("Exactly one semantic answer id per original question is required")
    for qid, value in answers.items():
        if value not in questions[qid]["options"]:
            raise AuditError("Invalid semantic answer id for " + qid)
    runs, raw, heldout = {}, {}, {}
    for run_id, records in submissions.items():
        mapping = body["mappings"][run_id]
        rows = []
        for r in records:
            qid, displayed = r["question_id"], r["primary"]
            semantic = None if displayed is None else mapping["display_to_semantic"][qid][displayed]
            q = questions[qid]
            rows.append({"question_id": qid, "person_id": q["person_id"],
                         "submitted_choice": semantic, "revealed_choice": answers[qid],
                         "option_count": len(q["options"]),
                         "correct": None if semantic is None else semantic == answers[qid]})
        eligible = [r for r in rows if questions[r["question_id"]]["partition"] == "test"
                    and spec["person_provenance"][r["person_id"]] == "unseen_declared"]
        runs[run_id] = {"all_rows_descriptive": grouped_metrics(rows),
                       "declared_unseen_test": grouped_metrics(eligible)}
        raw[run_id], heldout[run_id] = rows, eligible
    def comparisons(scored_rows):
        result = {}
        for rep in range(1, spec["repetitions"] + 1):
            prefix = f"r{rep:03d}/"
            for condition in CONDITIONS:
                fused = scored_rows[prefix + condition + "/fusion"]
                for arm in ("stem_only", "bazi", "ziwei"):
                    result[prefix + condition + "/fusion_vs_" + arm] = transitions(scored_rows[prefix + condition + "/" + arm], fused)
            for arm in ARMS:
                base = scored_rows[prefix + "original/" + arm]
                for condition in CONDITIONS[1:]:
                    result[prefix + condition + "/vs_original/" + arm] = transitions(base, scored_rows[prefix + condition + "/" + arm])
        return result
    def aggregate(scope):
        aggregated = {}
        for condition in CONDITIONS:
            for arm in ARMS:
                values = [runs[f"r{rep:03d}/{condition}/{arm}"][scope]
                          for rep in range(1, spec["repetitions"] + 1)]
                def mean(field):
                    items = [x[field] for x in values]
                    return statistics.mean(items) if all(x is not None for x in items) else None
                aggregated[condition + "/" + arm] = {"scope": scope, "repetitions": len(values),
                    "mean_full_accuracy": mean("accuracy_on_full_denominator"),
                    "mean_coverage": mean("coverage"),
                    "mean_person_macro_accuracy": mean("person_macro_accuracy"),
                    "distinct_person_count_not_multiplied_by_repetitions": values[0]["persons"]}
        return aggregated
    result = {"schema_version": SCHEMA, "trial_sha256": source["sha256"],
        "keys_sha256": digest(answers), "runs": runs, "comparisons_descriptive_all_rows": comparisons(raw),
        "comparisons_declared_unseen_test": comparisons(heldout),
        "all_predeclared_repetitions": aggregate("all_rows_descriptive"),
        "declared_unseen_test_all_repetitions": aggregate("declared_unseen_test"), "rows": raw,
        "prediction_accuracy_validated": False, "independent_blind_provenance_certified": False,
        "statistical_significance_assessed": False,
        "limitations": ["Known development and synthetic rows never become unseen validation.",
            "No best-run selection: all predeclared repetitions are frozen before reveal and reported.",
            "Questions and repetitions within one person are dependent, not additional people.",
            "Shuffled charts retain original biography keys only as a negative-control diagnostic; no new labeled biographies are created.",
            "Local hashes do not certify unseen answers, actual host settings, or model-training contamination.",
            "Review stems/options for identifying data and answer leakage; field checks cannot inspect semantic truth."]}
    if Path(destination).exists():
        raise FileExistsError(destination)
    registration = _batch_path(registry, spec["trial_id"], "controlled-scores")
    create_new(registration, result)
    create_new(destination, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--input", required=True)
    p.add_argument("--root", required=True)
    p.add_argument("--out", required=True)
    p = sub.add_parser("submit")
    p.add_argument("--manifest", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--input", required=True)
    p = sub.add_parser("score")
    p.add_argument("--manifest", required=True)
    p.add_argument("--answers", required=True)
    p.add_argument("--out", required=True)
    for p in sub.choices.values():
        p.add_argument("--registry", required=True)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            report = prepare(load_json(args.input), args.root, args.out, args.registry)
        elif args.command == "submit":
            report = {"submission_sha256": submit(args.manifest, args.run_id, load_json(args.input), args.registry)}
        else:
            result = score(args.manifest, args.answers, args.registry, args.out)
            report = {"trial_sha256": result["trial_sha256"], "runs": len(result["runs"]),
                      "prediction_accuracy_validated": False}
        print(canonical(report).decode("utf-8"))
        return 0
    except (AuditError, OSError, KeyError, TypeError) as error:
        print(canonical({"status": "invalid_trial", "error": str(error)}).decode("utf-8"))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

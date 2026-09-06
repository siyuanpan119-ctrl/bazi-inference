"""Read-only readiness checks for declared three-arm trials; no accuracy claims.

The output hashes actual artifacts. It neither certifies truthful reasoning nor
proves when an artifact existed. Existing submissions/scorers are not modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re


ARMS = ("v020-bazi", "v030-bazi", "v030-bazi-ziwei")
TRACE_FIELDS = ("natal_premise", "target", "luck_context", "supporting_condition",
                "competing_explanation", "differentiator", "counter_condition")
MODEL_FIELDS = ("model_id", "model_version", "reasoning_effort", "instructions_version")
EXCLUDED = {".git", "__pycache__", "node_modules", ".pytest_cache", ".mypy_cache",
            ".ruff_cache", ".venv", "venv", "private", ".private", "registry",
            ".registry", "answers", "predictions", "submissions", "reviews",
            "reports", "local-data", "private-data", "evaluations"}
PLACEHOLDER = re.compile(r"原题选项|原題選項|命题所问对象|命題所問對象|待填写|待填寫|待补充|TODO|TBD", re.I)
UNKNOWN = {"", "unknown", "unspecified", "n/a", "none", "未知", "未提供"}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def meaningful(value, minimum_length=4):
    return (isinstance(value, str) and len(value.strip()) >= minimum_length
            and value.strip().lower() not in UNKNOWN and not PLACEHOLDER.search(value))


def atom_text(value):
    # A real subject/action can be short: 命主, 母亲, 结婚. Length is not evidence.
    return meaningful(value, 1)


def complete_evidence(item, evidence_ids):
    if not isinstance(item, dict) or not item.get("id"):
        return False
    if meaningful(item.get("claim"), 2) and atom_text(item.get("source_ref")):
        return True
    if not meaningful(item.get("statement"), 2):
        return False
    if item.get("kind") == "traditional_hypothesis":
        basis = item.get("basis_ids")
        return (isinstance(basis, list) and bool(basis)
                and all(isinstance(ref, str) and ref in evidence_ids
                        and ref != item["id"] for ref in basis)
                and meaningful(item.get("warrant"), 2))
    return atom_text(item.get("source_group"))


def resolve_artifact(root, relative):
    if not isinstance(relative, str) or not relative:
        raise ValueError("An artifact path must be a nonempty string")
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Artifact path escapes --root: " + relative)
    return path


def excluded(part):
    lower = part.lower()
    data_stem = Path(lower).stem if Path(lower).suffix in {".json", ".jsonl", ".csv", ".db", ".txt"} else lower
    return (lower in EXCLUDED or data_stem.replace("_", "-") in EXCLUDED or lower.startswith("private-")
            or "-private-" in lower or lower.startswith(".private"))


def file_manifest(path, root):
    data = path.read_bytes()
    return {"path": path.relative_to(root).as_posix(), "bytes": len(data),
            "sha256": digest(data)}


def skill_manifest(skill_root):
    """Hash every eligible skill file, including source and reference contents."""
    if not (skill_root / "SKILL.md").is_file():
        raise ValueError("Skill snapshot has no SKILL.md: " + str(skill_root))
    rows = []
    for path in sorted(skill_root.rglob("*")):
        relative = path.relative_to(skill_root)
        if any(excluded(part) for part in relative.parts) or path.suffix in {".pyc", ".pyo"}:
            continue
        if path.is_symlink():
            raise ValueError("Skill snapshot must contain actual files, not symlinks: " + str(relative))
        if path.is_file():
            rows.append(file_manifest(path, skill_root))
    return {"files": rows, "sha256": digest(canonical(rows))}


def records_from(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        body = data.get("body", data)
        if isinstance(body, dict) and isinstance(body.get("records"), list):
            return body["records"]
    raise ValueError("Records must be a list or an object containing records")


def audit_records(records, expected_ids, combined):
    issues, ids, valid_primary, option_signature = [], [], 0, {}
    raw_scoring_possible = True
    for record in records:
        if not isinstance(record, dict):
            issues.append("nonobject_record")
            raw_scoring_possible = False
            continue
        qid = record.get("question_id")
        ids.append(qid)
        tag = str(qid)
        candidates = record.get("candidates", [])
        candidate_ids = []
        if not isinstance(candidates, list) or not candidates:
            issues.append(tag + ": missing_candidates")
            candidates = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                issues.append(tag + ": invalid_candidate")
                continue
            cid = candidate.get("id")
            candidate_ids.append(cid)
            atoms = candidate.get("atoms", [])
            if not isinstance(atoms, list) or not atoms:
                issues.append(tag + ": candidate_missing_atoms:" + str(cid))
                continue
            for atom in atoms:
                if (not isinstance(atom, dict)
                        or not atom_text(atom.get("subject"))
                        or not atom_text(atom.get("action"))
                        or not isinstance(atom.get("domain"), str)
                        or not atom.get("domain", "").strip()
                        or "year" not in atom
                        or PLACEHOLDER.search(str(atom.get("detail", "")))):
                    issues.append(tag + ": candidate_atom_incomplete_or_placeholder:" + str(cid))
        if (not candidate_ids or any(not isinstance(x, str) or not x for x in candidate_ids)
                or len(set(str(x) for x in candidate_ids)) != len(candidate_ids)):
            raw_scoring_possible = False
            issues.append(tag + ": invalid_candidate_ids")
        selection = record.get("selection")
        if not isinstance(selection, dict) or "primary" not in selection:
            issues.append(tag + ": missing_primary_selection")
            raw_scoring_possible = False
            selection = {}
        primary = selection.get("primary")
        if primary in candidate_ids and primary is not None:
            valid_primary += 1
        elif primary is not None:
            raw_scoring_possible = False
            issues.append(tag + ": invalid_primary_choice")
        evidence = record.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            issues.append(tag + ": empty_evidence_process_incomplete")
        elif not all(complete_evidence(e, {item.get("id") for item in evidence
                                           if isinstance(item, dict) and isinstance(item.get("id"), str)})
                     for e in evidence):
            issues.append(tag + ": evidence_missing_claim_or_source")
        trace = record.get("trace", {})
        for field in TRACE_FIELDS:
            if not isinstance(trace, dict) or not meaningful(trace.get(field), 4):
                issues.append(tag + ": trace_missing_or_placeholder:" + field)
        if record.get("seen_answers") is not False:
            issues.append(tag + ": answer_exposure_not_declared_false")
        if combined:
            status = record.get("ziwei_status")
            if status not in {"ready", "unavailable"} or "ziwei_raw_choice" not in record:
                issues.append(tag + ": missing_ziwei_diagnostic")
            raw = record.get("ziwei_raw_choice")
            if status == "ready" and raw not in candidate_ids:
                issues.append(tag + ": invalid_ziwei_raw_choice")
            if status == "unavailable" and raw is not None:
                issues.append(tag + ": unavailable_ziwei_must_have_null_raw_choice")
        option_signature[tag] = digest(canonical(candidates))
    if (len(ids) != len(expected_ids) or len(set(str(x) for x in ids)) != len(ids)
            or set(str(x) for x in ids) != set(expected_ids)):
        issues.append("question_set_missing_duplicate_or_changed")
        raw_scoring_possible = False
    return {"process_complete": not issues, "issues": issues,
            "raw_predictions_retained": True,
            "raw_accuracy_scoring_possible": raw_scoring_possible,
            "primary_selection_count": valid_primary,
            "full_denominator": len(expected_ids),
            "coverage": valid_primary / len(expected_ids) if expected_ids else None,
            "candidate_signatures": option_signature}


def preflight(plan_path, root):
    root = Path(root).resolve()
    plan_path = resolve_artifact(root, str(plan_path))
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    issues, model_values, arms, snapshots = [], [], {}, {}
    people = plan.get("question_persons", {})
    if not isinstance(people, dict) or not people or any(not isinstance(v, str) or not v for v in people.values()):
        raise ValueError("question_persons must declare the complete question-to-person mapping")
    expected_ids = list(people)
    if plan.get("expected_question_count") != len(expected_ids):
        issues.append("declared_full_question_count_mismatch")
    development = set(plan.get("development_person_ids", []))
    evaluation = set(plan.get("evaluation_person_ids", []))
    if evaluation != set(people.values()) or development & evaluation:
        issues.append("person_holdout_missing_or_development_overlap")
    required_policy = {"primary_only": True, "retain_all_questions": True, "report_coverage": True}
    if plan.get("scoring_policy") != required_policy:
        issues.append("scoring_policy_must_keep_primary_full_denominator_and_coverage")
    fusion = resolve_artifact(root, plan.get("fusion_policy_file"))
    if not meaningful(fusion.read_text(encoding="utf-8")):
        issues.append("fusion_policy_missing_or_placeholder")
    declarations = plan.get("arms", {})
    if set(declarations) != set(ARMS):
        raise ValueError("Declare exactly these arms: " + ", ".join(ARMS))
    for name in ARMS:
        arm = declarations[name]
        model = arm.get("host", {})
        if not isinstance(model, dict):
            model = {}
        if (any(not isinstance(model.get(k), str)
                or model[k].strip().lower() in UNKNOWN for k in MODEL_FIELDS)):
            issues.append(name + ": host_model_or_settings_unknown_not_comparable")
        model_values.append({key: model.get(key) for key in MODEL_FIELDS})
        skill_root = resolve_artifact(root, arm.get("skill_root"))
        record_path = resolve_artifact(root, arm.get("records_file"))
        records = records_from(json.loads(record_path.read_text(encoding="utf-8")))
        arms[name] = audit_records(records, expected_ids, name.endswith("ziwei"))
        if not arms[name]["process_complete"]:
            issues.append(name + ": process_incomplete")
        snapshots[name] = {"skill_root": skill_root.relative_to(root).as_posix(),
                           "skill": skill_manifest(skill_root),
                           "records": file_manifest(record_path, root), "host": model_values[-1]}
    if any(model != model_values[0] for model in model_values[1:]):
        issues.append("host_settings_differ_skill_effect_not_isolated")
    signatures = [arms[name]["candidate_signatures"] for name in ARMS]
    if any(value != signatures[0] for value in signatures[1:]):
        issues.append("candidate_content_differs_between_arms")
    snapshot = {"plan": file_manifest(plan_path, root), "fusion": file_manifest(fusion, root),
                "arms": snapshots}
    return {"schema_version": "trial-preflight-1.0", "trial_id": plan.get("trial_id"),
            "status": "process_complete" if not issues else "process_incomplete",
            "comparable_protocol_declared": not issues, "issues": issues, "arms": arms,
            "snapshot": snapshot, "snapshot_sha256": digest(canonical(snapshot)),
            "external_timestamp_verified": False, "reasoning_truth_verified": False,
            "prediction_accuracy_validated": False,
            "note": "Readiness and local content identity only; keep all raw choices for scoring."}


def verify_manifest(manifest, root):
    expected_hash = digest(canonical(manifest["snapshot"]))
    if manifest.get("snapshot_sha256") != expected_hash:
        return {"snapshot_matches": False, "reason": "manifest_internal_hash_mismatch"}
    current = preflight(manifest["snapshot"]["plan"]["path"], root)
    return {"snapshot_matches": current["snapshot_sha256"] == expected_hash,
            "reason": "contents_match" if current["snapshot_sha256"] == expected_hash else "actual_artifacts_changed",
            "external_timestamp_verified": False, "prediction_accuracy_validated": False}


def write_new_manifest(report, output):
    with Path(output).open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--plan")
    group.add_argument("--verify", type=Path)
    parser.add_argument("--output", type=Path, help="New file only; never overwrite a prior manifest")
    args = parser.parse_args()
    try:
        if args.verify:
            if args.output:
                parser.error("--output is only used with --plan")
            report = verify_manifest(json.loads(args.verify.read_text(encoding="utf-8")), args.root)
            print(json.dumps(report, ensure_ascii=False))
            return 0 if report["snapshot_matches"] else 1
        if not args.output:
            parser.error("--plan requires --output")
        report = preflight(args.plan, args.root)
        write_new_manifest(report, args.output)
        print(json.dumps({k: report[k] for k in ("status", "issues", "snapshot_sha256")}, ensure_ascii=False))
        return 0 if report["comparable_protocol_declared"] else 2
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"status": "invalid_artifact", "error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Score frozen, keyed dual-system answers without editing the frozen inputs.

The CLI defaults to 40 questions. ``score`` also accepts ``expected_count=N``
for other rounds; case_size controls only the reporting groups.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re


class AuditError(ValueError):
    """Invalid frozen evidence or an unsafe output destination."""


FIELDS = {"bazi": "bazi_primary", "ziwei": "ziwei_primary", "fusion": "final"}
RULINGS = "independent-and-fusion-rulings.json"
MANIFEST = "freeze-manifest.json"
CHOICES = set("ABCD")


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AuditError(f"Cannot read JSON {path}: {exc}") from exc


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def metric(hits, total):
    return {"correct": hits, "total": total,
            "accuracy": hits / total if total else None}


def validate_records(records, answers):
    n = len(answers)
    if not n or any(a not in CHOICES for a in answers):
        raise AuditError("Answer key must contain only A/B/C/D and be nonempty")
    if not isinstance(records, list) or len(records) != n:
        raise AuditError(f"Expected {n} records; missing or extra questions")
    ids = [r.get("question") if isinstance(r, dict) else None for r in records]
    if any(type(q) is not int for q in ids):
        raise AuditError("Question IDs must be integers")
    if len(set(ids)) != n:
        raise AuditError("Duplicate question IDs")
    if set(ids) != set(range(1, n + 1)):
        raise AuditError(f"Missing or out-of-range question IDs; expected 1..{n}")
    for r in records:
        for field in (*FIELDS.values(), "strongest_backup"):
            if not isinstance(r.get(field), str) or r[field] not in CHOICES:
                raise AuditError(f"Q{r['question']}: invalid {field}; expected A/B/C/D")


def score_records(records, answers, case_size=5):
    """Compute descriptive metrics for any N complete, uniquely numbered rows."""
    if type(case_size) is not int or case_size <= 0:
        raise AuditError("case_size must be a positive integer")
    validate_records(records, answers)
    rows = []
    for record in sorted(records, key=lambda r: r["question"]):
        key = answers[record["question"] - 1]
        rows.append({**record, "correct_key": key,
                     "correct": {**{s: record[f] == key for s, f in FIELDS.items()},
                                 "backup": record["strongest_backup"] == key}})

    def systems(subset):
        return {s: metric(sum(r["correct"][s] for r in subset), len(subset))
                for s in FIELDS}

    def group(subset):
        return {"count": len(subset), "questions": [r["question"] for r in subset],
                "systems": systems(subset)}

    def selection(subset):
        return {"count": len(subset), "questions": [r["question"] for r in subset]}

    n = len(rows)
    agreed = [r for r in rows if r["bazi_primary"] == r["ziwei_primary"]]
    disagreed = [r for r in rows if r["bazi_primary"] != r["ziwei_primary"]]
    changed = [r for r in rows if r["bazi_primary"] != r["final"]]
    gained = [r for r in changed if not r["correct"]["bazi"] and r["correct"]["fusion"]]
    lost = [r for r in changed if r["correct"]["bazi"] and not r["correct"]["fusion"]]
    still_wrong = [r for r in changed if not r["correct"]["bazi"] and not r["correct"]["fusion"]]
    backup_hits = [r for r in rows if r["correct"]["backup"]]
    covered = [r for r in rows if r["correct"]["fusion"] or r["correct"]["backup"]]
    recovered = [r for r in backup_hits if not r["correct"]["fusion"]]
    union = [r for r in rows if r["correct"]["bazi"] or r["correct"]["ziwei"]]
    statuses = sorted({str(r.get("support_state", "unrecorded")) for r in rows})
    totals = systems(rows)
    return {
        "question_count": n, "case_size": case_size, "systems": totals,
        "by_case": [{"case": start // case_size + 1, **group(rows[start:start + case_size])}
                    for start in range(0, n, case_size)],
        "agreement": {**group(agreed), "rate": len(agreed) / n},
        "disagreement": {**group(disagreed), "rate": len(disagreed) / n},
        "changes_from_bazi": {
            **selection(changed), "wrong_to_correct": selection(gained),
            "correct_to_wrong": selection(lost), "wrong_to_wrong": selection(still_wrong),
            "net_correct": len(gained) - len(lost),
            "accuracy_difference": (len(gained) - len(lost)) / n,
        },
        "coverage": {
            "fusion_primary": totals["fusion"],
            "backup_alone": {**selection(backup_hits), "total": n, "hit_rate": len(backup_hits) / n},
            "fusion_primary_or_backup": {**selection(covered), "total": n, "coverage": len(covered) / n},
            "backup_recovers_primary_errors": {
                **selection(recovered), "primary_errors": n - totals["fusion"]["correct"],
            },
            "bazi_or_ziwei_primary": {**selection(union), "total": n, "coverage": len(union) / n},
            "independent_system_top_two": None,
        },
        "by_support_state": {
            state: group([r for r in rows if str(r.get("support_state", "unrecorded")) == state])
            for state in statuses
        },
        "records": rows,
    }


def score(root, key_path, case_size=5, expected_count=40):
    """Verify every declared hash before scoring a read-only frozen round."""
    if type(expected_count) is not int or expected_count <= 0:
        raise AuditError("expected_count must be a positive integer")
    root, key_path = Path(root).resolve(), Path(key_path).resolve()
    manifest = read_json(root / MANIFEST)
    if not isinstance(manifest, dict):
        raise AuditError("Manifest must be an object")
    hashes = manifest.get("files_sha256")
    if not isinstance(hashes, dict) or RULINGS not in hashes:
        raise AuditError(f"Manifest must declare files_sha256 including {RULINGS}")
    verified = {}
    for name, expected in hashes.items():
        if not isinstance(name, str) or Path(name).is_absolute():
            raise AuditError("Manifest file names must be relative paths")
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise AuditError(f"Missing or outside-root frozen file: {name}")
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
            raise AuditError(f"Invalid SHA-256 declaration for {name}")
        actual = sha256(path)
        if actual != expected.lower():
            raise AuditError(f"Hash mismatch: {name}")
        verified[name] = actual

    key = read_json(key_path)
    if not isinstance(key, dict) or key.get("source") != "user-provided":
        raise AuditError("Key source must be user-provided")
    groups = key.get("answer_groups")
    if (not isinstance(groups, list) or not groups
            or any(not isinstance(g, str) or not g or set(g) - CHOICES for g in groups)):
        raise AuditError("answer_groups must contain nonempty A/B/C/D strings")
    answers = "".join(groups)
    if len(answers) != expected_count:
        raise AuditError(f"Expected {expected_count} key answers; got {len(answers)}")
    rulings = read_json(root / RULINGS)
    if not isinstance(rulings, dict):
        raise AuditError("Rulings must be an object")
    year = key.get("observation_year")
    if (type(year) is not int or year != manifest.get("observation_year")
            or year != rulings.get("observation_year")):
        raise AuditError("Key, manifest and rulings must agree on observation_year")
    records = rulings.get("records")
    validate_records(records, answers)
    sequence = "".join(r["final"] for r in sorted(records, key=lambda r: r["question"]))
    if manifest.get("answer_sequence") != sequence:
        raise AuditError("Frozen answer_sequence does not match records")
    result = score_records(records, answers, case_size)
    return {
        "schema_version": 1,
        "observation_year": year, "key_source": key["source"],
        "integrity": {
            "status": "verified", "root": str(root), "key_path": str(key_path),
            "key_sha256": sha256(key_path), "manifest_sha256": sha256(root / MANIFEST),
            "verified_files_sha256": verified,
            "question_ids_complete_unique": True, "frozen_sequence_matches": True,
        },
        "limitations": [
            "本格式未提供两系统各自推断阶段的独立冻结原记录；两栏仅按同上下文分栏评分，不能据此宣称统计独立或选出有效流派。",
            "一致票不自动增加证据强度；同一命例的题目共享资料，不能当作独立样本。",
            "首选加备选与两系统首选并集均为覆盖率，不是实际单选准确率；各系统独立备选未提供，故不计算各自top-2。",
            "support_state是原始支持状态，不转换成未记录的H/M/L或校准置信度。",
            "哈希一致只核验现有冻结材料的内部完整性，不独自证明冻结先于答案揭晓；开发集结果不能证明现实预测有效。",
        ],
        **result,
    }


def write_output(output, result, root, key_path):
    output = Path(output).resolve()
    root, key_path = Path(root).resolve(), Path(key_path).resolve()
    if output == key_path or output.is_relative_to(root):
        raise AuditError("Output must not overwrite the key or write inside the frozen root")
    if output.exists():
        raise AuditError(f"Output already exists; refusing to overwrite: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    except OSError as exc:
        raise AuditError(f"Cannot create output: {exc}") from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--key", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--case-size", type=int, default=5)
    parser.add_argument("--expected-questions", type=int, default=40)
    args = parser.parse_args(argv)
    try:
        result = score(args.root, args.key, args.case_size, args.expected_questions)
        write_output(args.output, result, args.root, args.key)
    except (AuditError, OSError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps({"output": str(args.output.resolve()), "systems": result["systems"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

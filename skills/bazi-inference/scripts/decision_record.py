#!/usr/bin/env python3
"""Check a small decision record; never rank candidates or validate prediction.

All claims are constituent requirements of their complete candidate. ``known``
means a user-reported real-world fact; ``supported`` means declared structural
support. Unknown claims in alternatives remain unknown, never contradicted.
Source and record references are opaque citations, not files loaded by this tool.
"""

import argparse
import json
from pathlib import Path


LIMITS = [
    "只校验字段、内部引用及显式声明；不验证自然语言推理、来源内容或引用文件是否存在。",
    "scope=discriminator 仅是作者声明；通过检查不证明区分条件有真实预测力。",
    "不计算概率、不自动选择或排除候选；relative_basis_declared 不是事件已发生或预测有效。",
    "无法发现未列出的候选；未提供 expected_temporal_branch_ids 时，不能检查遗漏的时间分支。",
    "不同 record_ref 不证明两套分析独立；同票不提高可信度。",
]


class _Schema:
    def __init__(self):
        self.errors = []

    def error(self, path, message, code="schema"):
        self.errors.append({"code": code, "path": path, "message": message})

    def obj(self, value, path, required, optional=()):
        if not isinstance(value, dict):
            self.error(path, "必须为对象。")
            return False
        for key in sorted(set(required) - value.keys()):
            self.error(f"{path}.{key}", "缺少字段。")
        for key in sorted(value.keys() - set(required) - set(optional)):
            self.error(f"{path}.{key}", "未知字段；请使用 v1 字段。")
        return True

    def string(self, value, path, empty=False, nullable=False):
        if nullable and value is None:
            return
        if not isinstance(value, str) or (not empty and not value.strip()):
            self.error(path, "必须为字符串。" if empty else "必须为非空字符串。")

    def choice(self, value, path, choices):
        if not isinstance(value, str) or value not in choices:
            self.error(path, "允许值：" + ", ".join(choices))

    def array(self, value, path, minimum=0):
        if not isinstance(value, list):
            self.error(path, "必须为数组。")
            return []
        if len(value) < minimum:
            self.error(path, f"至少需要 {minimum} 项。")
        return value

    def ids(self, value, path):
        values = self.array(value, path)
        seen = set()
        for i, item in enumerate(values):
            self.string(item, f"{path}[{i}]")
            if isinstance(item, str):
                if item in seen:
                    self.error(f"{path}[{i}]", "ID 重复。", "duplicate_id")
                seen.add(item)
        return values

    def records(self, values, path, required, optional=(), minimum=0):
        seen = set()
        for i, item in enumerate(self.array(values, path, minimum)):
            here = f"{path}[{i}]"
            if not self.obj(item, here, required, optional):
                continue
            identifier = item.get("id")
            self.string(identifier, here + ".id")
            if isinstance(identifier, str):
                if identifier in seen:
                    self.error(here + ".id", "ID 重复。", "duplicate_id")
                seen.add(identifier)
            yield item, here


def _validate(record):
    s = _Schema()
    required = ("schema_version", "target", "candidates", "evidence", "primary",
                "strongest_alternative", "comparison", "decision_mode")
    if not s.obj(record, "$", required,
                 ("temporal_branches", "expected_temporal_branch_ids", "fusion")):
        return s.errors
    if type(record.get("schema_version")) is not int or record["schema_version"] != 1:
        s.error("$.schema_version", "必须为整数 1。")
    target = record.get("target")
    if s.obj(target, "$.target", ("subject", "event_stage", "time_scope")):
        for key in ("subject", "event_stage", "time_scope"):
            s.string(target.get(key), f"$.target.{key}")
    for candidate, path in s.records(record.get("candidates"), "$.candidates",
                                     ("id", "claims"), minimum=2):
        for i, claim in enumerate(s.array(candidate.get("claims"), path + ".claims", 1)):
            here = f"{path}.claims[{i}]"
            if s.obj(claim, here, ("text", "state", "evidence_ids")):
                s.string(claim.get("text"), here + ".text")
                s.choice(claim.get("state"), here + ".state",
                         ("known", "supported", "unknown", "contradicted"))
                s.ids(claim.get("evidence_ids"), here + ".evidence_ids")
    for evidence, path in s.records(record.get("evidence"), "$.evidence",
                                    ("id", "kind", "scope", "source_ref", "statement")):
        s.choice(evidence.get("kind"), path + ".kind",
                 ("calculation", "user_fact", "traditional_interpretation"))
        s.choice(evidence.get("scope"), path + ".scope", ("background", "discriminator"))
        for key in ("source_ref", "statement"):
            s.string(evidence.get(key), f"{path}.{key}")
    for key in ("primary", "strongest_alternative"):
        s.string(record.get(key), f"$.{key}", nullable=True)
    s.choice(record.get("decision_mode"), "$.decision_mode", ("conditional", "forced_choice"))
    comparison = record.get("comparison")
    if s.obj(comparison, "$.comparison", ("against", "discriminator_ids", "why_distinguishes",
                                           "counterevidence", "required_unknowns")):
        for key in ("against", "discriminator_ids", "required_unknowns"):
            s.ids(comparison.get(key), f"$.comparison.{key}")
        for key in ("why_distinguishes", "counterevidence"):
            s.string(comparison.get(key), f"$.comparison.{key}", empty=True)
    if "expected_temporal_branch_ids" in record:
        s.ids(record["expected_temporal_branch_ids"], "$.expected_temporal_branch_ids")
    if "temporal_branches" in record:
        for branch, path in s.records(record["temporal_branches"], "$.temporal_branches", ("id", "primary"), ("note",)):
            s.string(branch.get("primary"), path + ".primary", nullable=True)
            if "note" in branch:
                s.string(branch["note"], path + ".note", empty=True)
    if "fusion" in record:
        fusion = record["fusion"]
        if s.obj(fusion, "$.fusion", ("bazi", "ziwei", "override_reason", "discriminator_ids"),
                 ("agreement_as_confidence",)):
            for system in ("bazi", "ziwei"):
                entry = fusion.get(system)
                if s.obj(entry, f"$.fusion.{system}", ("primary", "record_ref")):
                    s.string(entry.get("primary"), f"$.fusion.{system}.primary", nullable=True)
                    s.string(entry.get("record_ref"), f"$.fusion.{system}.record_ref")
            s.string(fusion.get("override_reason"), "$.fusion.override_reason", empty=True)
            s.ids(fusion.get("discriminator_ids"), "$.fusion.discriminator_ids")
            if "agreement_as_confidence" in fusion and type(fusion["agreement_as_confidence"]) is not bool:
                s.error("$.fusion.agreement_as_confidence", "必须为布尔值。")
    if s.errors:
        return s.errors

    candidate_ids = {item["id"] for item in record["candidates"]}
    evidence_ids = {item["id"] for item in record["evidence"]}

    def reference(value, allowed, path):
        if value is not None and value not in allowed:
            s.error(path, f"引用不存在的 ID：{value}", "bad_reference")

    for key in ("primary", "strongest_alternative"):
        reference(record[key], candidate_ids, f"$.{key}")
    for i, value in enumerate(comparison["against"]):
        reference(value, candidate_ids, f"$.comparison.against[{i}]")
    for i, value in enumerate(comparison["discriminator_ids"]):
        reference(value, evidence_ids, f"$.comparison.discriminator_ids[{i}]")
    for i, candidate in enumerate(record["candidates"]):
        for j, claim in enumerate(candidate["claims"]):
            for k, value in enumerate(claim["evidence_ids"]):
                reference(value, evidence_ids, f"$.candidates[{i}].claims[{j}].evidence_ids[{k}]")
    for i, branch in enumerate(record.get("temporal_branches", [])):
        reference(branch["primary"], candidate_ids, f"$.temporal_branches[{i}].primary")
    if "fusion" in record:
        for system in ("bazi", "ziwei"):
            reference(record["fusion"][system]["primary"], candidate_ids, f"$.fusion.{system}.primary")
        for i, value in enumerate(record["fusion"]["discriminator_ids"]):
            reference(value, evidence_ids, f"$.fusion.discriminator_ids[{i}]")
    return s.errors


def check_record(record):
    """Return JSON-serializable checks without mutating or selecting a candidate."""
    errors = _validate(record)
    data = record if isinstance(record, dict) else {}
    result = {
        "schema_version": 1, "record_valid": not errors,
        "effective_status": "invalid" if errors else "relative_basis_declared",
        "primary": data.get("primary"), "strongest_alternative": data.get("strongest_alternative"),
        "decision_mode": data.get("decision_mode"),
        "forced": data.get("decision_mode") == "forced_choice",
        "errors": errors, "issues": [], "unknown_claims": [], "limits": list(LIMITS),
    }
    if errors:
        return result

    def issue(code, path, message):
        result["issues"].append({"code": code, "path": path, "message": message})

    primary = record["primary"]
    candidates = {item["id"]: item for item in record["candidates"]}
    evidence = {item["id"]: item for item in record["evidence"]}
    comparison = record["comparison"]
    if primary is None:
        issue("primary_unresolved", "$.primary", "尚未形成首选。")
    if record["strongest_alternative"] is None or record["strongest_alternative"] == primary:
        issue("missing_alternative", "$.strongest_alternative", "须声明不同于首选的最强备选。")
    expected = set(candidates) - {primary}
    if set(comparison["against"]) != expected:
        issue("incomplete_comparison", "$.comparison.against",
              "须逐项比较全部其余候选；缺少：" + ", ".join(sorted(expected - set(comparison["against"])))
              + "；多列：" + ", ".join(sorted(set(comparison["against"]) - expected)))

    def discriminators(ids, path):
        usable = []
        for identifier in ids:
            if evidence[identifier]["scope"] == "background":
                issue("background_as_discriminator", path, f"{identifier} 被标为共有背景，不能升级成区分依据。")
            else:
                usable.append(identifier)
        return usable

    declared = discriminators(comparison["discriminator_ids"], "$.comparison.discriminator_ids")
    if not declared:
        issue("no_discriminator", "$.comparison.discriminator_ids", "未声明可用的相对区分条件。")
    elif primary is not None:
        primary_evidence = {identifier for claim in candidates[primary]["claims"] for identifier in claim["evidence_ids"]}
        if not primary_evidence.intersection(declared):
            issue("unlinked_primary_discriminator", "$.comparison.discriminator_ids",
                  "所声明区分依据均未被首选的任何子事实引用，须补齐依据与主张的联系。")
    if not comparison["why_distinguishes"].strip():
        issue("missing_comparison_reason", "$.comparison.why_distinguishes", "须说明首选相对其余候选的区别。")
    if not comparison["counterevidence"].strip():
        issue("missing_counterevidence_review", "$.comparison.counterevidence", "须记录最强反向条件；尚无已知反证也应明确写出。")
    if comparison["required_unknowns"]:
        issue("required_unknowns", "$.comparison.required_unknowns", "仍有必要但未知的前提；保持条件句，不能据缺失前提判反证。")
    for i, candidate in enumerate(record["candidates"]):
        for j, claim in enumerate(candidate["claims"]):
            path = f"$.candidates[{i}].claims[{j}]"
            if claim["state"] == "unknown":
                result["unknown_claims"].append({"candidate_id": candidate["id"], "claim_index": j, "text": claim["text"]})
                if candidate["id"] == primary:
                    issue("primary_unknown_claim", path, "首选完整选项仍有未知子事实；不能由其他子事实补齐。")
            elif not claim["evidence_ids"]:
                issue("missing_claim_evidence", path, "已知、支持或反向判断须引用依据；缺依据不等于事实不存在。")
            if claim["state"] == "known" and not any(evidence[x]["kind"] == "user_fact" for x in claim["evidence_ids"]):
                issue("known_without_user_fact", path, "现实已知须引用用户事实，不能仅由计算或传统解释升级。")
            if candidate["id"] == primary and claim["state"] == "contradicted":
                issue("primary_contradicted", path, "首选包含已声明的反向子事实，须处理冲突。")

    branches = record.get("temporal_branches", [])
    if "temporal_branches" in record and not branches:
        issue("empty_branch_review", "$.temporal_branches", "声明要检查分支，却未记录任何分支判断。")
    if "expected_temporal_branch_ids" in record:
        expected_branches = set(record["expected_temporal_branch_ids"])
        actual_branches = {branch["id"] for branch in branches}
        if expected_branches != actual_branches:
            issue("incomplete_branch_coverage", "$.temporal_branches",
                  "分支集合与声明的应审集合不符；缺少：" + ", ".join(sorted(expected_branches - actual_branches))
                  + "；多列：" + ", ".join(sorted(actual_branches - expected_branches)))
    for i, branch in enumerate(branches):
        if branch["primary"] is None or branch["primary"] != primary:
            issue("unstable_temporal_branch", f"$.temporal_branches[{i}].primary",
                  f"分支 {branch['id']} 的首选未定或不同；整体选择对时间分支不稳定。")

    if "fusion" in record:
        fusion = record["fusion"]
        bazi, ziwei = fusion["bazi"]["primary"], fusion["ziwei"]["primary"]
        usable = discriminators(fusion["discriminator_ids"], "$.fusion.discriminator_ids")
        if fusion["bazi"]["record_ref"] == fusion["ziwei"]["record_ref"]:
            issue("shared_system_record", "$.fusion", "两系统引用同一判断记录，未声明分别保留的分析底稿。")
        if bazi is None or ziwei is None:
            issue("unresolved_system", "$.fusion", "至少一套系统尚未形成独立首选。")
        if fusion.get("agreement_as_confidence", False):
            issue("agreement_not_confidence", "$.fusion.agreement_as_confidence", "同票不能作为提高可信度的依据。")
        if bazi != ziwei or primary not in (bazi, ziwei):
            if not fusion["override_reason"].strip() or not usable:
                issue("unsupported_override", "$.fusion", "改票或处理系统冲突须声明理由及区分条件；保留原有选择但分歧未解。")
            if set(usable) - set(declared):
                issue("override_outside_comparison", "$.fusion.discriminator_ids", "融合所用区分依据须纳入完整候选比较。")
    if result["forced"]:
        issue("forced_choice", "$.decision_mode", "按要求保留强制选择；该选择不能解除未知或分歧。")
    if result["issues"]:
        result["effective_status"] = "unresolved"
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        same_path = args.input.resolve() == args.output.resolve()
        if not same_path and args.input.exists() and args.output.exists():
            same_path = args.input.samefile(args.output)
    except (OSError, RuntimeError) as exc:
        parser.exit(2, f"无法核验输入输出路径：{exc}\n")
    if same_path:
        parser.exit(2, "输入与输出必须是不同文件；拒绝覆盖原始判断底稿。\n")
    try:
        record = json.loads(args.input.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        result = {"schema_version": 1, "record_valid": False, "effective_status": "invalid",
                  "errors": [{"code": "input_error", "path": "$", "message": str(exc)}],
                  "issues": [], "limits": list(LIMITS)}
    else:
        result = check_record(record)
    try:
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        parser.exit(2, f"无法写入检查结果：{exc}\n")
    return 0 if result["record_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

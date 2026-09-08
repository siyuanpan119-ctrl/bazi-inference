#!/usr/bin/env python3
"""Check a small decision record; never rank candidates or validate prediction.

All claims are constituent requirements of their complete candidate. ``known``
means a user-reported real-world fact; ``supported`` means declared structural
support. Unknown claims in alternatives remain unknown, never contradicted.
Source and record references are opaque citations, not files loaded by this tool.
The effective status describes evidence/record review, not permission to answer.
A retained primary remains the submitted choice when evidence is unresolved;
the host must label that choice as tentative or a guess rather than verified.
Version 2 (or v1 with candidate_reviews) additionally requires symmetric review;
it checks declared evidence status, not the truth of natural-language reasons.
Version 3 adds explicit target facets and declared rankings, including temporal
branches. Rankings are supplied by the author, never inferred by this checker.
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
    "v1 未提供 candidate_reviews 时只做旧版检查；列出 against 不证明已经逐候选审查。",
    "unknown/missing_support 只按显式标注检查；传统相容不证明医学诊断、法律状态或其他现实事实。",
    "effective_status 是证据审查状态，不是拒答开关；未决记录仍保留 primary 作为本轮选择，交付时须标明猜测或分歧。",
    "v3 的维度、排名及区分依据仍是作者声明；不验证事件预测力，也不能识别所有自然语言矛盾。",
    "quality_warnings 只提示复核，不证明内容错误，不改变交卷状态。",
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
            self.error(f"{path}.{key}", "未知字段；请使用文档列出的字段。")
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

    def ranking(self, value, path):
        # Empty and duplicate groups are review issues; bad types are errors.
        for i, group in enumerate(self.array(value, path)):
            for j, identifier in enumerate(self.array(group, f"{path}[{i}]")):
                self.string(identifier, f"{path}[{i}][{j}]")


def _validate(record):
    s = _Schema()
    v3 = isinstance(record, dict) and record.get("schema_version") == 3
    required = ("schema_version", "target", "candidates", "evidence", "primary",
                "strongest_alternative", "comparison", "decision_mode")
    if not s.obj(record, "$", required,
                 ("temporal_branches", "expected_temporal_branch_ids", "fusion", "candidate_reviews")
                 + (("ranking", "ranking_reason", "selection_basis") if v3 else ())):
        return s.errors
    if type(record.get("schema_version")) is not int or record["schema_version"] not in (1, 2, 3):
        s.error("$.schema_version", "必须为整数 1、2 或 3。")
    target = record.get("target")
    if s.obj(target, "$.target", ("subject", "event_stage", "time_scope"), ("facets",) if v3 else ()):
        for key in ("subject", "event_stage", "time_scope"):
            s.string(target.get(key), f"$.target.{key}")
        if v3 and "facets" in target:
            for i, facet in enumerate(s.array(target["facets"], "$.target.facets")):
                s.string(facet, f"$.target.facets[{i}]")
    if v3:
        if "ranking" in record:
            s.ranking(record["ranking"], "$.ranking")
        if "ranking_reason" in record:
            s.string(record["ranking_reason"], "$.ranking_reason", empty=True)
        if "selection_basis" in record:
            s.choice(record["selection_basis"], "$.selection_basis", ("relative_support", "guess"))
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
                                    ("id", "kind", "scope", "source_ref", "statement"), ("status",)):
        s.choice(evidence.get("kind"), path + ".kind",
                 ("calculation", "user_fact", "traditional_interpretation"))
        s.choice(evidence.get("scope"), path + ".scope", ("background", "discriminator"))
        for key in ("source_ref", "statement"):
            s.string(evidence.get(key), f"{path}.{key}")
        if "status" in evidence:
            s.choice(evidence["status"], path + ".status", ("available", "unknown", "missing_support"))
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
    if "candidate_reviews" in record:
        for review, path in s.records(record["candidate_reviews"], "$.candidate_reviews",
                                      ("id", "support_ids", "counterevidence_ids", "required_unknowns",
                                       "strongest_alternative", "discriminator_ids", "comparison"),
                                      ("facet_reviews",) if v3 else ()):
            for key in ("support_ids", "counterevidence_ids", "required_unknowns", "discriminator_ids"):
                s.ids(review.get(key), f"{path}.{key}")
            s.string(review.get("strongest_alternative"), path + ".strongest_alternative", nullable=True)
            s.string(review.get("comparison"), path + ".comparison", empty=True)
            if v3 and "facet_reviews" in review:
                for i, facet in enumerate(s.array(review["facet_reviews"], path + ".facet_reviews")):
                    here = f"{path}.facet_reviews[{i}]"
                    if s.obj(facet, here, ("facet", "state", "evidence_ids")):
                        s.string(facet.get("facet"), here + ".facet")
                        s.choice(facet.get("state"), here + ".state",
                                 ("relative_support", "shared_background", "unknown", "counterevidence"))
                        s.ids(facet.get("evidence_ids"), here + ".evidence_ids")
    if "expected_temporal_branch_ids" in record:
        s.ids(record["expected_temporal_branch_ids"], "$.expected_temporal_branch_ids")
    if "temporal_branches" in record:
        for branch, path in s.records(record["temporal_branches"], "$.temporal_branches", ("id", "primary"),
                                      ("note",) + (("ranking", "ranking_reason") if v3 else ())):
            s.string(branch.get("primary"), path + ".primary", nullable=True)
            if "note" in branch:
                s.string(branch["note"], path + ".note", empty=True)
            if v3:
                if "ranking" in branch:
                    s.ranking(branch["ranking"], path + ".ranking")
                if "ranking_reason" in branch:
                    s.string(branch["ranking_reason"], path + ".ranking_reason", empty=True)
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
    for i, review in enumerate(record.get("candidate_reviews", [])):
        path = f"$.candidate_reviews[{i}]"
        reference(review["id"], candidate_ids, path + ".id")
        reference(review["strongest_alternative"], candidate_ids, path + ".strongest_alternative")
        for key in ("support_ids", "counterevidence_ids", "discriminator_ids"):
            for j, value in enumerate(review[key]):
                reference(value, evidence_ids, f"{path}.{key}[{j}]")
        if v3:
            for j, facet in enumerate(review.get("facet_reviews", [])):
                # If target facets are missing, coverage issues explain the gap.
                if "facets" in target:
                    reference(facet["facet"], set(target["facets"]), f"{path}.facet_reviews[{j}].facet")
                for k, value in enumerate(facet["evidence_ids"]):
                    reference(value, evidence_ids, f"{path}.facet_reviews[{j}].evidence_ids[{k}]")
    for i, branch in enumerate(record.get("temporal_branches", [])):
        reference(branch["primary"], candidate_ids, f"$.temporal_branches[{i}].primary")
    if v3:
        ranked_entries = [(record, "$")] + [(branch, f"$.temporal_branches[{i}]")
                          for i, branch in enumerate(record.get("temporal_branches", []))]
        for entry, path in ranked_entries:
            for i, group in enumerate(entry.get("ranking", [])):
                for j, identifier in enumerate(group):
                    reference(identifier, candidate_ids, f"{path}.ranking[{i}][{j}]")
    if "fusion" in record:
        for system in ("bazi", "ziwei"):
            reference(record["fusion"][system]["primary"], candidate_ids, f"$.fusion.{system}.primary")
        for i, value in enumerate(record["fusion"]["discriminator_ids"]):
            reference(value, evidence_ids, f"$.fusion.discriminator_ids[{i}]")
    return s.errors


def _highest_other(ranking, excluded):
    """Return the first declared tier after excluding one candidate; no scoring."""
    for group in ranking:
        remaining = [identifier for identifier in group if identifier != excluded]
        if remaining:
            return remaining
    return []


def _check_v3(record, result, issue, discriminators):
    candidates = {item["id"]: item for item in record["candidates"]}
    candidate_ids = set(candidates)
    evidence = {item["id"]: item for item in record["evidence"]}
    facets = record["target"].get("facets", [])
    if not facets:
        issue("missing_target_facets", "$.target.facets", "v3 须列出题目实际需要区分的维度，不能为空。")
    if len(set(facets)) != len(facets):
        issue("duplicate_target_facet", "$.target.facets", "目标维度重复；每个维度只能声明一次。")

    def ranking_review(entry, path):
        ranking = entry.get("ranking", [])
        flattened = [identifier for group in ranking for identifier in group]
        complete = True
        if not ranking or any(not group for group in ranking):
            issue("empty_ranking", path + ".ranking", "须填写由高到低的非空候选层；无法区分时可全部并列。")
            complete = False
        if len(set(flattened)) != len(flattened):
            issue("duplicate_ranked_candidate", path + ".ranking", "排名中的候选重复；每个候选只出现一次。")
            complete = False
        if set(flattened) != candidate_ids:
            issue("incomplete_ranking", path + ".ranking", "排名必须覆盖全部候选一次；缺少："
                  + ", ".join(sorted(candidate_ids - set(flattened))))
            complete = False
        if not entry.get("ranking_reason", "").strip():
            issue("missing_ranking_reason", path + ".ranking_reason", "须填写该次实际排序或并列的理由，备注不能替代。")
            complete = False
        if entry["primary"] is not None and (not ranking or entry["primary"] not in ranking[0]):
            issue("primary_outside_top_rank", path + ".primary", "首选与最高排名层不一致；保留原选择，须复核声明。")
        return complete

    ranking_review(record, "$")
    ranking = record.get("ranking", [])
    allowed = _highest_other(ranking, record["primary"])
    if record["strongest_alternative"] not in allowed:
        issue("alternative_rank_mismatch", "$.strongest_alternative",
              "最强备选须来自排除首选后的最高层；不自动替换原字段。")
    primary_facets = set()
    for i, review in enumerate(record.get("candidate_reviews", [])):
        path = f"$.candidate_reviews[{i}]"
        if review["strongest_alternative"] not in _highest_other(ranking, review["id"]):
            issue("review_alternative_rank_mismatch", path + ".strongest_alternative",
                  "该候选的最强备选须来自排除它之后的最高层；并列层内可声明任一主要对照。")
        entries = review.get("facet_reviews", [])
        covered = [entry["facet"] for entry in entries]
        if not entries or set(covered) != set(facets):
            issue("incomplete_facet_reviews", path + ".facet_reviews", "须按同一组目标维度审查该候选；未知可明确记 unknown。")
        if len(covered) != len(set(covered)):
            issue("duplicate_facet_review", path + ".facet_reviews", "该候选的每个维度只能审查一次。")
        claim_support = {identifier for claim in candidates[review["id"]]["claims"]
                         if claim["state"] in ("known", "supported") for identifier in claim["evidence_ids"]}
        linked = ((set(review["support_ids"]) & claim_support)
                  | set(review["counterevidence_ids"]))
        for j, entry in enumerate(entries):
            here = f"{path}.facet_reviews[{j}]"
            ids = entry["evidence_ids"]
            state = entry["state"]
            if state == "unknown":
                if review["id"] == record["primary"]:
                    issue("primary_unknown_facet", here, "首选仍有未知的目标维度；其他维度的相对支持不能补齐。")
                continue
            if not ids:
                issue("missing_facet_evidence", here + ".evidence_ids", "背景、相对支持或反证声明须连接依据；缺少依据可保持 unknown。")
            if any(evidence[x].get("status", "available") != "available" for x in ids):
                issue("unavailable_as_facet_evidence", here + ".evidence_ids", "未知或缺少支持的依据不能升级为背景、相对支持或反证。")
            if state == "relative_support":
                usable = set(discriminators(ids, here + ".evidence_ids"))
                linked_usable = usable & linked & set(review["discriminator_ids"])
                if not linked_usable:
                    issue("unlinked_facet_discriminator", here,
                          "相对支持须引用可用区分依据，并连接本候选支持/反证及其 discriminator_ids；共有背景不能替代。")
                if set(ids) - linked:
                    issue("unlinked_facet_evidence", here + ".evidence_ids", "维度依据须连接本候选的支持或反证。")
                if review["id"] == record["primary"]:
                    primary_facets.update(linked_usable)
            elif state == "counterevidence" and set(ids) - set(review["counterevidence_ids"]):
                issue("unlinked_facet_counterevidence", here + ".evidence_ids", "维度反向条件须连接本候选的 counterevidence_ids；反向结构不等于选项事实不存在。")
            elif state == "shared_background" and any(evidence[x]["scope"] != "background" for x in ids):
                issue("facet_scope_mismatch", here + ".evidence_ids", "共有背景维度须引用 scope=background 的声明。")

    if "selection_basis" not in record:
        issue("missing_selection_basis", "$.selection_basis", "v3 须声明本轮选择依据为 relative_support 或 guess。")
    elif record["selection_basis"] == "guess":
        issue("guess_choice", "$.selection_basis", "本轮已提交猜测；不补造区分依据，不升级为已验证事实。")
    elif (not ranking or len(ranking[0]) != 1
          or not primary_facets.intersection(record["comparison"]["discriminator_ids"])):
        issue("guess_required", "$.selection_basis", "首层并列或缺少连接目标维度的首选区分依据；保留选择，须标 guess。")

    branches = record.get("temporal_branches", [])
    if "temporal_branches" in record and "expected_temporal_branch_ids" not in record:
        issue("missing_expected_temporal_branches", "$.expected_temporal_branch_ids", "v3 声明时间分支时须同时列出应审分支集合。")
    result["temporal_review_statuses"] = []
    for i, branch in enumerate(branches):
        path = f"$.temporal_branches[{i}]"
        complete = ranking_review(branch, path)
        branch_ranking = branch.get("ranking", [])
        tied = bool(branch_ranking and len(branch_ranking[0]) > 1)
        result["temporal_review_statuses"].append({
            "id": branch["id"],
            "status": "incomplete" if not complete else ("compared_tie" if tied else "compared"),
        })
        if complete and tied:
            issue("temporal_branch_tie", path + ".ranking", "该分支已完成声明比较且首层并列；并列不等于漏填分析。")
        elif complete and branch["primary"] is None:
            issue("missing_branch_choice", path + ".primary", "该分支已填写排序，但未声明分支首选。")


def check_record(record):
    """Return JSON-serializable checks without mutating or selecting a candidate."""
    errors = _validate(record)
    data = record if isinstance(record, dict) else {}
    v3 = data.get("schema_version") == 3
    symmetric = data.get("schema_version") in (2, 3) or "candidate_reviews" in data
    result = {
        "schema_version": 1, "record_valid": not errors,
        "review_standard": "target_facets_v3" if v3 else ("symmetric" if symmetric else "legacy_v1"),
        "effective_status": "invalid" if errors else "relative_basis_declared",
        "submission_status": "invalid_record" if errors else (
            "submitted" if data.get("primary") is not None else "missing_choice"),
        "primary": data.get("primary"), "strongest_alternative": data.get("strongest_alternative"),
        "decision_mode": data.get("decision_mode"),
        "forced": data.get("decision_mode") == "forced_choice",
        "errors": errors, "issues": [], "quality_warnings": [], "unknown_claims": [], "limits": list(LIMITS),
    }
    if errors:
        return result

    def issue(code, path, message):
        result["issues"].append({"code": code, "path": path, "message": message})

    repeated_comparisons = {}
    for review in record.get("candidate_reviews", []):
        comparison_text = review["comparison"].strip()
        if comparison_text:
            repeated_comparisons.setdefault(comparison_text, []).append(review["id"])
    for identifiers in repeated_comparisons.values():
        if len(identifiers) > 1:
            result["quality_warnings"].append({
                "code": "repeated_candidate_comparison", "path": "$.candidate_reviews",
                "candidate_ids": identifiers,
                "message": "这些候选的非空比较文字完全重复，请复核是否逐项比较；重复也可能真实反映相同结论，不阻断交卷。",
            })

    primary = record["primary"]
    candidates = {item["id"]: item for item in record["candidates"]}
    evidence = {item["id"]: item for item in record["evidence"]}
    comparison = record["comparison"]
    if primary is None:
        issue("primary_unresolved", "$.primary", "尚未提交首选；题目要求作答时应填写适用的最终选择，证据不足另标猜测。")
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
            if evidence[identifier].get("status", "available") != "available":
                issue("unavailable_as_discriminator", path,
                      f"{identifier} 声明为未知或缺少正面支持，不能用作区分事件的依据。")
            elif evidence[identifier]["scope"] == "background":
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
        issue("missing_comparison_reason", "$.comparison.why_distinguishes", "须说明候选的实际比较；没有区别时明确写无法区分及最终选择属猜测，不编造区别。")
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
            if claim["state"] != "unknown" and any(
                    evidence[x].get("status", "available") != "available" for x in claim["evidence_ids"]):
                issue("unavailable_as_claim_evidence", path,
                      "未知或缺少正面支持不能充当已知、支持或反向事实的依据。")
            if claim["state"] == "known" and not any(evidence[x]["kind"] == "user_fact" for x in claim["evidence_ids"]):
                issue("known_without_user_fact", path, "现实已知须引用用户事实，不能仅由计算或传统解释升级。")
            if candidate["id"] == primary and claim["state"] == "contradicted":
                issue("primary_contradicted", path, "首选包含已声明的反向子事实，须处理冲突。")

    if symmetric:
        reviews = {item["id"]: item for item in record.get("candidate_reviews", [])}
        missing = set(candidates) - set(reviews)
        if missing:
            issue("incomplete_candidate_reviews", "$.candidate_reviews",
                  "同一标准须审查所有候选（含保留的基线首选）；缺少：" + ", ".join(sorted(missing)))
        for i, review in enumerate(record.get("candidate_reviews", [])):
            path = f"$.candidate_reviews[{i}]"
            candidate = candidates[review["id"]]
            alternative = review["strongest_alternative"]
            if alternative is None or alternative == review["id"]:
                issue("missing_review_alternative", path + ".strongest_alternative",
                      "每个候选须声明另一个最强备选，不得因其不是首选而省略。")
            if not review["comparison"].strip():
                issue("missing_candidate_comparison", path + ".comparison",
                      "须记录该候选相对最强备选的实际比较；可以明确较弱或无法区分。")
            for key in ("support_ids", "counterevidence_ids"):
                for identifier in review[key]:
                    if evidence[identifier].get("status", "available") != "available":
                        role = "support" if key == "support_ids" else "counterevidence"
                        issue("unavailable_as_" + role, path + "." + key,
                              f"{identifier} 声明为未知或缺少正面支持，不能当作支持或反证。")
            if set(review["support_ids"]) & set(review["counterevidence_ids"]):
                issue("ambiguous_evidence_role", path,
                      "同一依据同时列作该候选的支持和反证；须拆清不同主张及作用。")
            support = {x for claim in candidate["claims"] if claim["state"] in ("known", "supported")
                       for x in claim["evidence_ids"]}
            counter = {x for claim in candidate["claims"] if claim["state"] == "contradicted"
                       for x in claim["evidence_ids"]}
            unknowns = {claim["text"] for claim in candidate["claims"] if claim["state"] == "unknown"}
            unknown_evidence = {x for claim in candidate["claims"] if claim["state"] == "unknown"
                                for x in claim["evidence_ids"]}
            if unknown_evidence.intersection(review["counterevidence_ids"]):
                issue("unknown_claim_as_counterevidence", path + ".counterevidence_ids",
                      "未知子事实所引依据不能同时用作该候选反证；若作用于不同子事实，须拆清依据及作用。")
            if not support.issubset(review["support_ids"]) or not counter.issubset(review["counterevidence_ids"]):
                issue("incomplete_evidence_review", path,
                      "候选已声明的支持及反向子事实依据须分别纳入审查，基线与备选同标准。")
            if set(review["support_ids"]) - support:
                issue("unlinked_candidate_support", path + ".support_ids",
                      "支持须连接该候选已知或相容的子事实，不能用其他候选的缺口补齐。")
            if not unknowns.issubset(review["required_unknowns"]):
                issue("incomplete_unknown_review", path + ".required_unknowns",
                      "候选未知子事实须按原 text 列入未知清单，不能漏掉或改作反证。")
            reviewed_discriminators = discriminators(review["discriminator_ids"], path + ".discriminator_ids")
            pair_evidence = set(review["support_ids"]) | set(review["counterevidence_ids"])
            if alternative in reviews:
                pair_evidence.update(reviews[alternative]["support_ids"])
                pair_evidence.update(reviews[alternative]["counterevidence_ids"])
            if set(reviewed_discriminators) - pair_evidence:
                issue("unlinked_review_discriminator", path + ".discriminator_ids",
                      "比较依据须连接本候选或所比较备选的支持/反证；不能只列一个无关联的 ID。")
            if review["id"] == primary:
                if alternative != record["strongest_alternative"]:
                    issue("inconsistent_primary_alternative", path + ".strongest_alternative",
                          "首选审查与总记录须采用同一最强备选。")
                if set(declared) - set(reviewed_discriminators):
                    issue("unreviewed_primary_discriminator", path + ".discriminator_ids",
                          "总记录首选所用区分依据须纳入它自己的对称审查。")
                if review["required_unknowns"]:
                    issue("review_required_unknowns", path + ".required_unknowns",
                          "首选仍有必要未知前提；保留条件，不能由备选更弱补足。")

    if v3:
        _check_v3(record, result, issue, discriminators)

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
                issue("unsupported_override", "$.fusion", "缺少解决系统冲突的理由或区分条件；本轮 primary 仍是提交选择，证据分歧未解，不表示基线优先或自动回滚。")
            if set(usable) - set(declared):
                issue("override_outside_comparison", "$.fusion.discriminator_ids", "融合所用区分依据须纳入完整候选比较。")
    if result["forced"]:
        issue("forced_choice", "$.decision_mode", "按要求保留强制选择；该选择不能解除未知或分歧。")
    if result["issues"]:
        result["effective_status"] = "unresolved"
    return result


def render_summary(record):
    """Render structured declarations without inferring a choice or rewriting prose."""
    result = check_record(record)
    if not result["record_valid"]:
        raise ValueError("无法为字段或引用无效的记录生成候选摘要。")

    def label(value):
        return "未填写" if value is None else str(value).replace("\n", " ").replace("\r", " ")

    lines = ["# 判断记录摘要", "", f"首选（原记录）：{label(record['primary'])}",
             f"最强备选（原记录）：{label(record['strongest_alternative'])}",
             f"交卷状态：{result['submission_status']}；证据审查：{result['effective_status']}"]
    ranking = record.get("ranking", [])
    if record["schema_version"] == 3:
        rank_text = " > ".join(" = ".join(label(x) for x in group) for group in ranking)
        lines.extend([f"声明排名：{rank_text or '未填写'}", f"选择依据：{record.get('selection_basis', '未填写')}",
                      "", "排序说明：", record.get("ranking_reason", "")])
    else:
        lines.append("旧版记录：未执行 v3 目标维度及排名检查。")
    lines.extend(["", "总体比较（原文）：", record["comparison"]["why_distinguishes"]])
    reviews = {review["id"]: review for review in record.get("candidate_reviews", [])}
    ordered = list(dict.fromkeys(identifier for group in ranking for identifier in group))
    ordered.extend(identifier for identifier in reviews if identifier not in ordered)
    for identifier in ordered:
        if identifier not in reviews:
            lines.extend(["", f"## 候选 {label(identifier)}", "未填写候选审查。"])
            continue
        review = reviews[identifier]
        # Titles use structured fields; prose remains verbatim for human review.
        lines.extend(["", f"## 候选 {label(identifier)}；主要对照：{label(review['strongest_alternative'])}",
                      "", review["comparison"]])
        if record["schema_version"] == 3:
            allowed = _highest_other(ranking, identifier)
            lines.extend(["", "排名允许的最强备选：" + "、".join(label(x) for x in allowed)])
            for facet in review.get("facet_reviews", []):
                lines.append(f"- {label(facet['facet'])}：{facet['state']}；依据："
                             + ("、".join(label(x) for x in facet["evidence_ids"]) or "无"))
    for branch in record.get("temporal_branches", []):
        branch_ranking = " > ".join(" = ".join(label(x) for x in group) for group in branch.get("ranking", []))
        lines.extend(["", f"## 时间分支 {label(branch['id'])}", "",
                      f"分支首选（原记录）：{label(branch['primary'])}",
                      f"声明排名：{branch_ranking or '未填写'}", "", "排序说明（原文）：",
                      branch.get("ranking_reason", "未填写")])
        if branch.get("note"):
            lines.extend(["", "分支备注（原文）：", branch["note"]])
    if result["issues"]:
        lines.extend(["", "## 待复核的一致性问题", ""])
        lines.extend("- " + item["message"] for item in result["issues"])
    if result["quality_warnings"]:
        lines.extend(["", "## 文字复核提示", ""])
        lines.extend("- " + item["message"] for item in result["quality_warnings"])
    lines.extend(["", "此摘要只展示声明与一致性检查，不验证预测或现实事实。", ""])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--markdown", type=Path, help="可选：从同一结构字段生成摘要；不改写比较正文。")
    args = parser.parse_args(argv)
    try:
        paths = [args.input, args.output] + ([args.markdown] if args.markdown else [])
        same_path = any(left.resolve() == right.resolve()
                        or (left.exists() and right.exists() and left.samefile(right))
                        for i, left in enumerate(paths) for right in paths[i + 1:])
    except (OSError, RuntimeError) as exc:
        parser.exit(2, f"无法核验输入输出路径：{exc}\n")
    if same_path:
        parser.exit(2, "输入、检查输出及 Markdown 必须是不同文件；拒绝覆盖原始判断底稿或其他输出。\n")
    try:
        record = json.loads(args.input.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        result = {"schema_version": 1, "record_valid": False, "effective_status": "invalid",
                  "submission_status": "invalid_record",
                  "errors": [{"code": "input_error", "path": "$", "message": str(exc)}],
                  "issues": [], "quality_warnings": [], "limits": list(LIMITS)}
    else:
        result = check_record(record)
    try:
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if args.markdown:
            summary = render_summary(record) if result["record_valid"] else "记录无效，未生成候选摘要；请检查 JSON 错误记录。\n"
            args.markdown.write_text(summary, encoding="utf-8")
    except OSError as exc:
        parser.exit(2, f"无法写入检查结果：{exc}\n")
    return 0 if result["record_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

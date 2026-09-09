"""Record consistency tests using synthetic data; not prediction-validity tests."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from itertools import permutations
from pathlib import Path

from decision_record import check_record, render_summary


ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_COMPARISON_OVERVIEW = (
    "这是用于文字检查的合成总述：已有材料仅说明共同背景，尚未建立具体条件之间的对应关系。"
    "各项必要前提均须分别核对；缺少支持不能证明另一候选成立，也不能转为任何候选的反证。"
    "如果复核后仍无可用区别，可以诚实保留未知与并列，并注明所提交首选只是本轮猜测。"
)


def record():
    return {
        "schema_version": 1,
        "target": {"subject": "合成人物", "event_stage": "合成事项", "time_scope": "T1"},
        "candidates": [
            {"id": "A", "claims": [{"text": "合成条件甲", "state": "supported", "evidence_ids": ["D"]}]},
            {"id": "B", "claims": [{"text": "合成条件乙", "state": "unknown", "evidence_ids": []}]},
            {"id": "C", "claims": [{"text": "合成条件丙", "state": "unknown", "evidence_ids": []}]},
        ],
        "evidence": [
            {"id": "D", "kind": "traditional_interpretation", "scope": "discriminator",
             "source_ref": "synthetic:condition", "statement": "仅用于检查字段的条件声明。"},
            {"id": "BG", "kind": "calculation", "scope": "background",
             "source_ref": "synthetic:background", "statement": "各候选共有的合成背景。"},
        ],
        "primary": "A", "strongest_alternative": "B", "decision_mode": "conditional",
        "comparison": {"against": ["B", "C"], "discriminator_ids": ["D"],
                       "why_distinguishes": "声明甲有不同于乙、丙的条件，内容需人工审核。",
                       "counterevidence": "若所声明条件不成立，须撤回首选。", "required_unknowns": []},
    }


def codes(result):
    return {item["code"] for item in result["issues"]}


def add_fusion(data, bazi="A", ziwei="B", **values):
    data["fusion"] = {
        "bazi": {"primary": bazi, "record_ref": "synthetic:bazi-record"},
        "ziwei": {"primary": ziwei, "record_ref": "synthetic:ziwei-record"},
        "override_reason": "", "discriminator_ids": [], **values,
    }


def symmetric_record(version=2):
    data = record()
    data["schema_version"] = version
    data["candidate_reviews"] = [
        {"id": "A", "support_ids": ["D"], "counterevidence_ids": [], "required_unknowns": [],
         "strongest_alternative": "B", "discriminator_ids": ["D"],
         "comparison": "甲声明有 D，乙尚无对应支持；乙未知仍不是反证。"},
        {"id": "B", "support_ids": [], "counterevidence_ids": [], "required_unknowns": ["合成条件乙"],
         "strongest_alternative": "A", "discriminator_ids": ["D"],
         "comparison": "乙尚无独有支持，甲声明有 D；不能由此认定乙未发生。"},
        {"id": "C", "support_ids": [], "counterevidence_ids": [], "required_unknowns": ["合成条件丙"],
         "strongest_alternative": "A", "discriminator_ids": [],
         "comparison": "丙与甲的现实事件仍待查；无已知反证，不声明丙胜出。"},
    ]
    return data


def ranked_record():
    data = symmetric_record(3)
    data["target"]["facets"] = ["合成事件取得"]
    data.update(ranking=[["A"], ["B"], ["C"]], ranking_reason="按合成条件 D 的声明排序。",
                selection_basis="relative_support")
    for review in data["candidate_reviews"]:
        review["facet_reviews"] = [{"facet": "合成事件取得", "state": "unknown", "evidence_ids": []}]
    data["candidate_reviews"][0]["facet_reviews"][0].update(state="relative_support", evidence_ids=["D"])
    return data


def tied_record():
    data = ranked_record()
    data.update(ranking=[["A", "B", "C"]], ranking_reason="全部候选均缺少区分条件，实际比较后并列。",
                selection_basis="guess", decision_mode="forced_choice")
    data["comparison"].update(discriminator_ids=[], required_unknowns=["合成条件甲"],
                              why_distinguishes="无法区分，保留 A 作为本轮猜测。")
    data["candidates"][0]["claims"][0].update(state="unknown", evidence_ids=[])
    for review in data["candidate_reviews"]:
        review["discriminator_ids"] = []
        review["facet_reviews"][0].update(state="unknown", evidence_ids=[])
    data["candidate_reviews"][0].update(support_ids=[], required_unknowns=["合成条件甲"])
    return data


def add_branch_basis(data):
    """Declare separate synthetic calculation fields; no real examples or labels."""
    for branch in data["temporal_branches"]:
        identifier = "CALC_" + branch["id"]
        data["evidence"].append({"id": identifier, "kind": "calculation", "scope": "background",
                                 "source_ref": "synthetic:branches#" + branch["id"],
                                 "statement": "该合成分支的独立计算字段，内容需人工审核。"})
        branch["basis_evidence_ids"] = [identifier]


class DecisionRecordTests(unittest.TestCase):
    def test_valid_record_preserves_choice_and_does_not_disprove_unknown_alternatives(self):
        data = record()
        before = deepcopy(data)
        result = check_record(data)
        self.assertEqual(result["effective_status"], "relative_basis_declared")
        self.assertEqual(result["primary"], "A")
        self.assertEqual([item["candidate_id"] for item in result["unknown_claims"]], ["B", "C"])
        self.assertNotIn("probability", result)
        self.assertEqual(data, before)

    def test_background_cannot_be_promoted_even_with_another_discriminator(self):
        data = record()
        data["comparison"]["discriminator_ids"] = ["D", "BG"]
        result = check_record(data)
        self.assertTrue(result["record_valid"])
        self.assertEqual(result["effective_status"], "unresolved")
        self.assertIn("background_as_discriminator", codes(result))

    def test_discriminator_needs_a_link_to_primary_claims(self):
        data = record()
        data["candidates"][0]["claims"][0]["evidence_ids"] = ["BG"]
        result = check_record(data)
        self.assertTrue(result["record_valid"])
        self.assertIn("unlinked_primary_discriminator", codes(result))

    def test_missing_primary_prerequisite_does_not_become_counterevidence(self):
        data = record()
        data["candidates"][0]["claims"].append({"text": "必要子事实未知", "state": "unknown", "evidence_ids": []})
        result = check_record(data)
        self.assertIn("primary_unknown_claim", codes(result))
        self.assertNotIn("primary_contradicted", codes(result))
        self.assertEqual(result["primary"], "A")
        self.assertEqual(data["candidates"][0]["claims"][1]["state"], "unknown")

    def test_declared_required_unknowns_downgrade(self):
        data = record()
        data["comparison"]["required_unknowns"] = ["尚未知道的必要前提"]
        self.assertIn("required_unknowns", codes(check_record(data)))

    def test_whole_comparison_must_cover_more_than_strongest_alternative(self):
        data = record()
        data["comparison"]["against"] = ["B"]
        self.assertIn("incomplete_comparison", codes(check_record(data)))

    def test_expected_branches_detect_missing_review(self):
        data = record()
        data["expected_temporal_branch_ids"] = ["before", "after"]
        data["temporal_branches"] = [{"id": "before", "primary": "A"}]
        self.assertIn("incomplete_branch_coverage", codes(check_record(data)))

    def test_stable_branches_can_include_time_notes(self):
        data = record()
        data["expected_temporal_branch_ids"] = ["before", "after"]
        data["temporal_branches"] = [
            {"id": "before", "primary": "A", "note": "合成边界前，保留实际日期区间。"},
            {"id": "after", "primary": "A", "note": "合成边界后，保留实际日期区间。"},
        ]
        self.assertEqual(check_record(data)["effective_status"], "relative_basis_declared")

    def test_branch_disagreement_or_unknown_preserves_primary(self):
        for branch_primary in ("B", None):
            with self.subTest(primary=branch_primary):
                data = record()
                data["temporal_branches"] = [{"id": "before", "primary": "A"}, {"id": "after", "primary": branch_primary}]
                result = check_record(data)
                self.assertIn("unstable_temporal_branch", codes(result))
                self.assertEqual(result["primary"], "A")

    def test_fusion_conflict_needs_reason_and_declared_discriminator(self):
        for reason, evidence_ids in (("", []), ("仅仅改票", []), ("以共有背景改票", ["BG"])):
            with self.subTest(reason=reason):
                data = record()
                add_fusion(data, override_reason=reason, discriminator_ids=evidence_ids)
                result = check_record(data)
                self.assertIn("unsupported_override", codes(result))
                self.assertEqual(result["primary"], "A")

    def test_fusion_validates_only_declared_conditions_and_agreement_never_scores(self):
        data = record()
        add_fusion(data, override_reason="声明比较条件 D 对本阶段有区别。", discriminator_ids=["D"])
        self.assertEqual(check_record(data)["effective_status"], "relative_basis_declared")
        add_fusion(data, ziwei="A")
        self.assertEqual(check_record(data)["effective_status"], "relative_basis_declared")
        data["fusion"]["agreement_as_confidence"] = True
        self.assertIn("agreement_not_confidence", codes(check_record(data)))

    def test_changing_both_systems_choice_requires_override(self):
        data = record()
        add_fusion(data, bazi="B", ziwei="B")
        self.assertIn("unsupported_override", codes(check_record(data)))

    def test_forced_choice_always_stays_unresolved_and_retains_primary(self):
        data = record()
        data["decision_mode"] = "forced_choice"
        result = check_record(data)
        self.assertEqual(result["effective_status"], "unresolved")
        self.assertTrue(result["forced"])
        self.assertEqual(result["primary"], "A")
        self.assertTrue(result["record_valid"])

    def test_unknown_choice_is_submitted_without_becoming_supported(self):
        data = symmetric_record()
        data['decision_mode'] = 'forced_choice'
        data['candidates'][0]['claims'][0].update(state='unknown', evidence_ids=[])
        data['comparison'].update(discriminator_ids=[], required_unknowns=['合成条件甲'])
        for review in data['candidate_reviews']:
            review['discriminator_ids'] = []
        data['candidate_reviews'][0].update(support_ids=[], required_unknowns=['合成条件甲'])
        before = deepcopy(data)
        result = check_record(data)
        self.assertTrue(result['record_valid'])
        self.assertEqual(result['submission_status'], 'submitted')
        self.assertEqual(result['effective_status'], 'unresolved')
        self.assertEqual(result['primary'], 'A')
        self.assertIn('primary_unknown_claim', codes(result))
        self.assertEqual(data, before)

    def test_missing_choice_and_invalid_record_have_distinct_submission_states(self):
        data = record()
        data['primary'] = None
        data['comparison']['against'] = ['A', 'B', 'C']
        result = check_record(data)
        self.assertTrue(result['record_valid'])
        self.assertEqual(result['submission_status'], 'missing_choice')
        self.assertEqual(result['effective_status'], 'unresolved')
        data['primary'] = 'nonexistent'
        result = check_record(data)
        self.assertFalse(result['record_valid'])
        self.assertEqual(result['submission_status'], 'invalid_record')

    def test_bad_internal_references_are_schema_errors(self):
        for location in ("primary", "claim", "comparison", "branch", "fusion"):
            with self.subTest(location=location):
                data = record()
                if location == "primary":
                    data["primary"] = "missing"
                elif location == "claim":
                    data["candidates"][0]["claims"][0]["evidence_ids"] = ["missing"]
                elif location == "comparison":
                    data["comparison"]["against"] = ["missing"]
                elif location == "branch":
                    data["temporal_branches"] = [{"id": "t", "primary": "missing"}]
                else:
                    add_fusion(data, discriminator_ids=["missing"])
                result = check_record(data)
                self.assertEqual(result["effective_status"], "invalid")
                self.assertIn("bad_reference", {item["code"] for item in result["errors"]})

    def test_types_duplicates_and_unknown_fields_are_rejected_without_crashing(self):
        malformed = [None, [], {}, {**record(), "schema_version": True}, {**record(), "target": []}]
        duplicate = record()
        duplicate["candidates"][1]["id"] = "A"
        malformed.append(duplicate)
        typo = record()
        typo["comparison"]["confidence"] = 0.9
        malformed.append(typo)
        bad_state = record()
        bad_state["candidates"][0]["claims"][0]["state"] = []
        malformed.append(bad_state)
        for data in malformed:
            with self.subTest(data=data):
                self.assertFalse(check_record(data)["record_valid"])

    def test_calculated_support_cannot_become_known_event(self):
        data = record()
        data["candidates"][0]["claims"][0]["state"] = "known"
        self.assertIn("known_without_user_fact", codes(check_record(data)))

    def test_symmetric_v2_and_opt_in_v1_preserve_primary_and_allow_weak_alternatives(self):
        self.assertEqual(check_record(record())["review_standard"], "legacy_v1")
        for version in (1, 2):
            with self.subTest(version=version):
                data = symmetric_record(version)
                before = deepcopy(data)
                result = check_record(data)
                self.assertTrue(result["record_valid"])
                self.assertEqual(result["effective_status"], "relative_basis_declared")
                self.assertEqual(result["review_standard"], "symmetric")
                self.assertEqual(result["primary"], "A")
                self.assertEqual(data, before)

    def test_v2_missing_whole_or_partial_reviews_is_unresolved_not_legacy(self):
        for keep in (None, [], [0, 1]):
            with self.subTest(keep=keep):
                data = symmetric_record()
                if keep is None:
                    del data["candidate_reviews"]
                else:
                    data["candidate_reviews"] = [data["candidate_reviews"][i] for i in keep]
                result = check_record(data)
                self.assertTrue(result["record_valid"])
                self.assertEqual(result["effective_status"], "unresolved")
                self.assertIn("incomplete_candidate_reviews", codes(result))

    def test_against_list_cannot_replace_any_candidates_actual_comparison(self):
        for i in range(3):
            with self.subTest(candidate=i):
                data = symmetric_record()
                data["candidate_reviews"][i]["comparison"] = "  "
                self.assertIn("missing_candidate_comparison", codes(check_record(data)))

    def test_strongest_alternative_cannot_be_missing_or_self(self):
        for value in (None, "B"):
            data = symmetric_record()
            data["candidate_reviews"][1]["strongest_alternative"] = value
            self.assertIn("missing_review_alternative", codes(check_record(data)))
        data = symmetric_record()
        data["candidate_reviews"][0]["strongest_alternative"] = "C"
        self.assertIn("inconsistent_primary_alternative", codes(check_record(data)))

    def test_retaining_baseline_in_fusion_has_no_review_exemption(self):
        for ziwei in ("A", "B"):
            with self.subTest(ziwei=ziwei):
                data = symmetric_record()
                add_fusion(data, ziwei=ziwei, override_reason="按同一条件 D 比较后保留甲。", discriminator_ids=["D"])
                self.assertEqual(check_record(data)["effective_status"], "relative_basis_declared")
                data["candidate_reviews"] = data["candidate_reviews"][1:]
                result = check_record(data)
                self.assertEqual(result["primary"], "A")
                self.assertIn("incomplete_candidate_reviews", codes(result))

    def test_any_candidates_declared_support_counter_and_unknowns_must_be_reviewed(self):
        data = symmetric_record()
        data["candidate_reviews"][0]["support_ids"] = []
        self.assertIn("incomplete_evidence_review", codes(check_record(data)))
        data = symmetric_record()
        data["candidate_reviews"][1]["required_unknowns"] = []
        self.assertIn("incomplete_unknown_review", codes(check_record(data)))
        data = symmetric_record()
        data["candidates"][2]["claims"][0].update(state="contradicted", evidence_ids=["BG"])
        data["candidate_reviews"][2]["required_unknowns"] = []
        self.assertIn("incomplete_evidence_review", codes(check_record(data)))
        data["candidate_reviews"][2]["counterevidence_ids"] = ["BG"]
        self.assertEqual(check_record(data)["effective_status"], "relative_basis_declared")

    def test_unknown_enrollment_or_missing_learning_support_cannot_prove_noncompletion(self):
        for status in ("unknown", "missing_support"):
            with self.subTest(status=status):
                data = symmetric_record()
                data["evidence"].append({"id": "U", "kind": "traditional_interpretation", "scope": "discriminator",
                                         "status": status, "source_ref": "synthetic:education",
                                         "statement": "入学情况未知，或未找到学习支持；不是未毕业的事实。"})
                data["candidates"][1]["claims"][0].update(text="已完成课程", state="unknown", evidence_ids=["U"])
                review = data["candidate_reviews"][1]
                review["required_unknowns"] = ["已完成课程"]
                self.assertEqual(check_record(data)["effective_status"], "relative_basis_declared")
                review["counterevidence_ids"] = ["U"]
                result = check_record(data)
                self.assertIn("unavailable_as_counterevidence", codes(result))
                self.assertEqual(data["candidates"][1]["claims"][0]["state"], "unknown")
                data["candidates"][1]["claims"][0]["state"] = "contradicted"
                self.assertIn("unavailable_as_claim_evidence", codes(check_record(data)))
                data["candidates"][0]["claims"][0].update(text="未毕业", evidence_ids=["U"])
                data["candidate_reviews"][0].update(support_ids=["U"], discriminator_ids=["U"])
                data["comparison"]["discriminator_ids"] = ["U"]
                result = check_record(data)
                self.assertIn("unavailable_as_support", codes(result))
                self.assertIn("unavailable_as_discriminator", codes(result))

    def test_primary_unknown_remains_unresolved_even_if_every_alternative_is_weaker(self):
        data = symmetric_record()
        data["candidates"][0]["claims"].append({"text": "此前持续修读", "state": "unknown", "evidence_ids": []})
        data["candidate_reviews"][0]["required_unknowns"] = ["此前持续修读"]
        result = check_record(data)
        self.assertIn("primary_unknown_claim", codes(result))
        self.assertIn("review_required_unknowns", codes(result))
        self.assertNotIn("primary_contradicted", codes(result))

    def test_unknown_claim_reference_cannot_double_as_its_candidates_counterevidence(self):
        data = symmetric_record()
        data["candidates"][1]["claims"][0]["evidence_ids"] = ["D"]
        data["candidate_reviews"][1]["counterevidence_ids"] = ["D"]
        result = check_record(data)
        self.assertIn("unknown_claim_as_counterevidence", codes(result))
        self.assertEqual(result["effective_status"], "unresolved")
        self.assertEqual(result["primary"], "A")

    def test_medical_and_legal_compatibility_cannot_become_known_facts(self):
        for text in ("已确诊某疾病", "已依法登记离婚"):
            with self.subTest(claim=text):
                data = symmetric_record()
                data["candidates"][0]["claims"][0].update(text=text, state="supported")
                compatible = check_record(data)
                self.assertEqual(compatible["effective_status"], "relative_basis_declared")
                self.assertNotIn("verified_fact", compatible)
                data["candidates"][0]["claims"][0]["state"] = "known"
                self.assertIn("known_without_user_fact", codes(check_record(data)))

    def test_candidate_order_does_not_change_conclusion_or_issue_codes(self):
        for missing_review in (False, True):
            data = symmetric_record()
            if missing_review:
                data["candidate_reviews"].pop()
            expected = check_record(data)
            for order in permutations(data["candidates"]):
                permuted = deepcopy(data)
                permuted["candidates"] = list(order)
                permuted["candidate_reviews"].reverse()
                permuted["comparison"]["against"].reverse()
                actual = check_record(permuted)
                self.assertEqual(actual["effective_status"], expected["effective_status"])
                self.assertEqual(actual["primary"], expected["primary"])
                self.assertEqual(codes(actual), codes(expected))

    def test_symmetric_bad_references_duplicates_and_types_are_invalid(self):
        for location in ("candidate", "alternative", "evidence", "duplicate", "array", "entry", "status"):
            with self.subTest(location=location):
                data = symmetric_record()
                if location == "candidate":
                    data["candidate_reviews"][0]["id"] = "absent"
                elif location == "alternative":
                    data["candidate_reviews"][0]["strongest_alternative"] = "absent"
                elif location == "evidence":
                    data["candidate_reviews"][0]["counterevidence_ids"] = ["absent"]
                elif location == "duplicate":
                    data["candidate_reviews"].append(deepcopy(data["candidate_reviews"][0]))
                elif location == "array":
                    data["candidate_reviews"] = {}
                elif location == "entry":
                    data["candidate_reviews"] = [None]
                else:
                    data["evidence"][0]["status"] = []
                self.assertFalse(check_record(data)["record_valid"])

    def test_cli_exits_zero_for_unresolved_and_nonzero_for_invalid(self):
        example = (ROOT / "assets/decision-record.example.json").read_text(encoding="utf-8")
        for text, expected_code, expected_status in ((example, 0, "unresolved"), ("{broken", 2, "invalid")):
            with self.subTest(status=expected_status), tempfile.TemporaryDirectory() as directory:
                source, output = Path(directory) / "input.json", Path(directory) / "output.json"
                source.write_text(text, encoding="utf-8")
                proc = subprocess.run([sys.executable, str(ROOT / "scripts/decision_record.py"),
                                       "--input", str(source), "--output", str(output)], capture_output=True, text=True)
                self.assertEqual(proc.returncode, expected_code, proc.stderr)
                checked = json.loads(output.read_text(encoding="utf-8"))
                self.assertEqual(checked["effective_status"], expected_status)
                if expected_status == "invalid":
                    self.assertEqual(checked["submission_status"], "invalid_record")

    def test_cli_refuses_same_file_including_resolved_paths_and_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.json"
            original = json.dumps(record(), ensure_ascii=False)
            source.write_text(original, encoding="utf-8")
            (root / "subdir").mkdir()
            symlink, hardlink = root / "symlink.json", root / "hardlink.json"
            symlink.symlink_to(source)
            os.link(source, hardlink)
            for output in (source, root / "subdir" / ".." / "input.json", symlink, hardlink):
                with self.subTest(output=output):
                    proc = subprocess.run([sys.executable, str(ROOT / "scripts/decision_record.py"),
                                           "--input", str(source), "--output", str(output)], capture_output=True, text=True)
                    self.assertEqual(proc.returncode, 2)
                    self.assertIn("拒绝覆盖", proc.stderr)
                    self.assertEqual(source.read_text(encoding="utf-8"), original)


class RankedDecisionRecordTests(unittest.TestCase):
    def test_v3_adds_explicit_standard_and_does_not_mutate_or_score(self):
        data = ranked_record()
        before = deepcopy(data)
        result = check_record(data)
        self.assertTrue(result["record_valid"])
        self.assertEqual(result["review_standard"], "target_facets_v3")
        self.assertEqual(result["effective_status"], "relative_basis_declared")
        self.assertEqual(result["submission_status"], "submitted")
        self.assertEqual(result["primary_ranking_status"], "relative_basis_declared")
        self.assertEqual(result["alternative_role"], "ranked_alternative")
        self.assertEqual(result["review_completion_status"], "declared_complete")
        self.assertNotIn("probability", result)
        self.assertEqual(data, before)

    def test_ranking_misalignment_retains_submitted_primary(self):
        data = ranked_record()
        data["ranking"] = [["B"], ["C"], ["A"]]
        result = check_record(data)
        self.assertTrue(result["record_valid"])
        self.assertIn("primary_outside_top_rank", codes(result))
        self.assertIn("review_alternative_rank_mismatch", codes(result))
        self.assertEqual(result["primary"], "A")
        self.assertEqual(result["submission_status"], "submitted")
        self.assertEqual(result["effective_status"], "unresolved")
        self.assertEqual(result["primary_ranking_status"], "inconsistent")
        self.assertEqual(result["review_completion_status"], "needs_review")

    def test_alternatives_use_highest_remaining_tier_and_primary_fields_stay_consistent(self):
        data = ranked_record()
        data["strongest_alternative"] = "C"
        self.assertIn("alternative_rank_mismatch", codes(check_record(data)))
        data["ranking"] = [["A"], ["B", "C"]]
        result = check_record(data)
        self.assertNotIn("alternative_rank_mismatch", codes(result))
        self.assertIn("inconsistent_primary_alternative", codes(result))
        data["candidate_reviews"][0]["strongest_alternative"] = "C"
        self.assertEqual(check_record(data)["effective_status"], "relative_basis_declared")

    def test_missing_empty_and_duplicate_ranks_are_issues_not_invalid_records(self):
        for ranking, expected in (([["A"], ["B"]], "incomplete_ranking"),
                                  ([["A"], ["B", "C", "A"]], "duplicate_ranked_candidate"),
                                  ([["A"], [], ["B", "C"]], "empty_ranking"),
                                  ([], "empty_ranking")):
            with self.subTest(ranking=ranking):
                data = ranked_record()
                data["ranking"] = ranking
                result = check_record(data)
                self.assertTrue(result["record_valid"])
                self.assertIn(expected, codes(result))
                self.assertEqual(result["submission_status"], "submitted")
        data = ranked_record()
        del data["ranking"]
        self.assertIn("empty_ranking", codes(check_record(data)))

    def test_bad_ranking_types_and_references_are_errors(self):
        for ranking in (None, "A > B", ["A", "B"], [["A"], [2]], [["A", "B", "absent"]]):
            with self.subTest(ranking=ranking):
                data = ranked_record()
                data["ranking"] = ranking
                self.assertFalse(check_record(data)["record_valid"])

    def test_missing_v3_declarations_are_issues_while_v2_remains_compatible(self):
        for key, expected in (("ranking_reason", "missing_ranking_reason"),
                              ("selection_basis", "missing_selection_basis"),
                              ("candidate_reviews", "incomplete_candidate_reviews")):
            data = ranked_record()
            del data[key]
            result = check_record(data)
            self.assertTrue(result["record_valid"])
            self.assertIn(expected, codes(result))
        data = ranked_record()
        del data["target"]["facets"]
        self.assertIn("missing_target_facets", codes(check_record(data)))
        for version in (1, 2):
            data = symmetric_record(version)
            result = check_record(data)
            self.assertTrue(result["record_valid"])
            self.assertEqual(result["review_standard"], "symmetric")
            self.assertNotIn("temporal_review_statuses", result)
            self.assertIn("未执行 v3", render_summary(data))

    def test_facets_must_be_unique_and_all_candidates_cover_each(self):
        data = ranked_record()
        data["target"]["facets"].append("合成量级")
        self.assertIn("incomplete_facet_reviews", codes(check_record(data)))
        data = ranked_record()
        data["target"]["facets"].append("合成事件取得")
        result = check_record(data)
        self.assertTrue(result["record_valid"])
        self.assertIn("duplicate_target_facet", codes(result))
        data = ranked_record()
        data["candidate_reviews"][0]["facet_reviews"] *= 2
        result = check_record(data)
        self.assertTrue(result["record_valid"])
        self.assertIn("duplicate_facet_review", codes(result))
        data = ranked_record()
        del data["candidate_reviews"][1]["facet_reviews"]
        self.assertIn("incomplete_facet_reviews", codes(check_record(data)))

    def test_unknown_or_background_facet_does_not_establish_target_discriminator(self):
        for state, ids in (("unknown", []), ("shared_background", ["BG"]),
                           ("relative_support", ["BG"])):
            with self.subTest(state=state):
                data = ranked_record()
                data["candidate_reviews"][0]["facet_reviews"][0].update(state=state, evidence_ids=ids)
                result = check_record(data)
                self.assertTrue(result["record_valid"])
                self.assertIn("guess_required", codes(result))
                self.assertEqual(result["primary_ranking_status"], "unsupported")
                if state == "relative_support":
                    self.assertIn("background_as_discriminator", codes(result))
                    self.assertIn("unlinked_facet_discriminator", codes(result))

    def test_facet_discriminator_must_be_available_declared_and_linked_to_own_review(self):
        for change in ("unavailable", "unlinked", "undeclared"):
            with self.subTest(change=change):
                data = ranked_record()
                if change == "unavailable":
                    data["evidence"][0]["status"] = "unknown"
                elif change == "unlinked":
                    data["candidate_reviews"][0]["support_ids"] = []
                else:
                    data["candidate_reviews"][0]["discriminator_ids"] = []
                result = check_record(data)
                self.assertIn("unlinked_facet_discriminator", codes(result))
                self.assertIn("guess_required", codes(result))
                self.assertEqual(result["primary_ranking_status"], "unsupported")
        data = ranked_record()
        data["candidate_reviews"][1]["facet_reviews"][0].update(state="relative_support", evidence_ids=["D"])
        self.assertIn("unlinked_facet_discriminator", codes(check_record(data)))

    def test_unique_top_without_comparison_discriminator_is_not_relative_support(self):
        data = ranked_record()
        data["comparison"]["discriminator_ids"] = []
        result = check_record(data)
        self.assertEqual(result["submission_status"], "submitted")
        self.assertIn("no_discriminator", codes(result))
        self.assertEqual(result["primary_ranking_status"], "unsupported")
        self.assertEqual(result["primary"], "A")

    def test_facet_evidence_and_names_have_validated_references(self):
        for key, value in (("facet", "absent"), ("evidence_ids", ["absent"]), ("state", "certain")):
            data = ranked_record()
            data["candidate_reviews"][0]["facet_reviews"][0][key] = value
            self.assertFalse(check_record(data)["record_valid"])

    def test_partial_target_support_cannot_fill_unknown_magnitude(self):
        data = ranked_record()
        data["target"]["facets"].append("合成量级")
        for review in data["candidate_reviews"]:
            review["facet_reviews"].append({"facet": "合成量级", "state": "unknown", "evidence_ids": []})
        result = check_record(data)
        self.assertTrue(result["record_valid"])
        self.assertEqual(result["submission_status"], "submitted")
        self.assertEqual(result["effective_status"], "unresolved")
        self.assertIn("primary_unknown_facet", codes(result))
        self.assertNotIn("guess_required", codes(result))
        self.assertEqual(result["primary_ranking_status"], "relative_basis_declared")
        self.assertEqual(result["review_completion_status"], "declared_complete")

    def test_relative_ranking_survives_unknown_clause_without_promoting_it_to_fact(self):
        data = ranked_record()
        data["candidates"][0]["claims"].append({"text": "附带细节未知", "state": "unknown", "evidence_ids": []})
        data["candidate_reviews"][0]["required_unknowns"] = ["附带细节未知"]
        data["comparison"]["required_unknowns"] = ["附带细节未知"]
        before = deepcopy(data)
        result = check_record(data)
        self.assertEqual(result["primary_ranking_status"], "relative_basis_declared")
        self.assertEqual(result["effective_status"], "unresolved")
        self.assertEqual(result["submission_status"], "submitted")
        self.assertEqual(result["review_completion_status"], "declared_complete")
        self.assertNotIn("guess_required", codes(result))
        self.assertNotIn("primary_contradicted", codes(result))
        self.assertIn("未知既不补成事实", " ".join(result["review_actions"]))
        self.assertEqual(data, before)

    def test_independent_countercondition_does_not_force_unknown_claim_to_contradicted(self):
        for facet_state in ("counterevidence", "relative_support"):
            with self.subTest(state=facet_state):
                data = ranked_record()
                review = data["candidate_reviews"][1]
                review["facet_reviews"][0].update(state=facet_state, evidence_ids=["D"])
                result = check_record(data)
                expected = "unlinked_facet_counterevidence" if facet_state == "counterevidence" else "unlinked_facet_discriminator"
                self.assertIn(expected, codes(result))
                # D is a separately declared opposing condition, not proof that B is false.
                review["counterevidence_ids"] = ["D"]
                before = deepcopy(data)
                result = check_record(data)
                self.assertNotIn(expected, codes(result))
                self.assertEqual(data["candidates"][1]["claims"][0]["state"], "unknown")
                self.assertEqual(result["submission_status"], "submitted")
                self.assertEqual(data, before)
                data["candidates"][1]["claims"][0]["evidence_ids"] = ["D"]
                self.assertIn("unknown_claim_as_counterevidence", codes(check_record(data)))

    def test_all_unknown_tie_is_a_valid_submitted_guess_without_promoting_claims(self):
        data = tied_record()
        before = deepcopy(data)
        result = check_record(data)
        self.assertTrue(result["record_valid"])
        self.assertEqual(result["submission_status"], "submitted")
        self.assertEqual(result["effective_status"], "unresolved")
        self.assertEqual(result["primary"], "A")
        self.assertIn("guess_choice", codes(result))
        self.assertNotIn("guess_required", codes(result))
        self.assertEqual(len(result["unknown_claims"]), 3)
        self.assertEqual(result["primary_ranking_status"], "tied")
        self.assertEqual(result["alternative_role"], "tied_comparator")
        self.assertEqual(result["review_completion_status"], "needs_review")
        self.assertIn("empty_candidate_basis", {x["code"] for x in result["quality_warnings"]})
        self.assertIn("漏读已有计算", " ".join(result["review_actions"]))
        self.assertIn("不强求非空", " ".join(result["review_actions"]))
        summary = render_summary(data)
        self.assertIn("并列对照（原记录）：B", summary)
        self.assertIn("首选未被区分为更优", summary)
        self.assertIn("声明完整性：需要补审", summary)
        self.assertNotIn("最强备选", summary)
        self.assertIn("仍须交付单一首选", " ".join(result["review_actions"]))
        self.assertEqual(data, before)
        data["selection_basis"] = "relative_support"
        self.assertIn("guess_required", codes(check_record(data)))

    def test_reviewed_shared_background_still_allows_tie_without_empty_basis_warning(self):
        data = tied_record()
        data["candidates"][0]["claims"].append({"text": "合成共有背景", "state": "supported", "evidence_ids": ["BG"]})
        data["candidate_reviews"][0]["support_ids"] = ["BG"]
        data["candidate_reviews"][0]["facet_reviews"][0].update(state="shared_background", evidence_ids=["BG"])
        result = check_record(data)
        self.assertEqual(result["primary_ranking_status"], "tied")
        self.assertEqual(result["submission_status"], "submitted")
        self.assertEqual(result["review_completion_status"], "declared_complete")
        self.assertNotIn("empty_candidate_basis", {x["code"] for x in result["quality_warnings"]})
        self.assertIn("不表示实质推断已完成", render_summary(data))

    def test_temporal_notes_do_not_replace_comparison_but_completed_tie_is_recognized(self):
        data = ranked_record()
        data["expected_temporal_branch_ids"] = ["before", "after"]
        data["temporal_branches"] = [
            {"id": "before", "primary": "A", "note": "声称已经比较全部候选。"},
            {"id": "after", "primary": None, "ranking": [["A", "B", "C"]],
             "ranking_reason": "此合成分支全部未知，实际比较后并列。"},
        ]
        add_branch_basis(data)
        before = deepcopy(data)
        result = check_record(data)
        self.assertTrue(result["record_valid"])
        self.assertEqual(result["temporal_review_statuses"], [
            {"id": "before", "status": "incomplete"}, {"id": "after", "status": "compared_tie"}])
        self.assertIn("missing_ranking_reason", codes(result))
        self.assertIn("temporal_branch_tie", codes(result))
        self.assertEqual(result["submission_status"], "submitted")
        self.assertEqual(data, before)
        rendered = render_summary(data)
        self.assertIn("时间分支 after", rendered)
        self.assertIn("声明排名：A = B = C", rendered)
        self.assertIn("分支首选（原记录）：未填写", rendered)
        self.assertIn(data["temporal_branches"][1]["ranking_reason"], rendered)

    def test_v3_branches_require_expected_set_and_full_rankings(self):
        data = ranked_record()
        data["temporal_branches"] = [{"id": "before", "primary": "A", "ranking": [["A"], ["B"]],
                                      "ranking_reason": "仅填部分候选。"}]
        result = check_record(data)
        self.assertIn("missing_expected_temporal_branches", codes(result))
        self.assertIn("incomplete_ranking", codes(result))
        data["expected_temporal_branch_ids"] = ["before", "after"]
        self.assertIn("incomplete_branch_coverage", codes(check_record(data)))
        data["temporal_branches"][0]["ranking"] = [["A"], ["B", "absent"]]
        self.assertFalse(check_record(data)["record_valid"])

    def test_fully_compared_stable_branches_remain_relative_declarations(self):
        data = ranked_record()
        data["expected_temporal_branch_ids"] = ["before", "after"]
        data["temporal_branches"] = [
            {"id": identifier, "primary": "A", "ranking": deepcopy(data["ranking"]),
             "ranking_reason": "该合成分支以 D 比较后排序。"} for identifier in ("before", "after")]
        add_branch_basis(data)
        result = check_record(data)
        self.assertEqual(result["effective_status"], "relative_basis_declared")
        self.assertEqual([x["status"] for x in result["temporal_review_statuses"]], ["compared", "compared"])
        self.assertEqual(result["primary_ranking_status"], "relative_basis_declared")
        self.assertEqual(result["review_completion_status"], "declared_complete")
        self.assertNotIn("copied_temporal_comparison", {x["code"] for x in result["quality_warnings"]})

    def test_copied_branches_without_distinct_computation_remain_submitted_and_need_review(self):
        for variant in ("absent", "same_id", "same_source", "interpretation", "unavailable"):
            with self.subTest(variant=variant):
                data = ranked_record()
                data["expected_temporal_branch_ids"] = ["before", "after"]
                data["temporal_branches"] = [
                    {"id": identifier, "primary": "A", "ranking": deepcopy(data["ranking"]),
                     "ranking_reason": "复用同一段合成比较理由。"} for identifier in ("before", "after")]
                if variant != "absent":
                    add_branch_basis(data)
                    if variant == "same_id":
                        data["temporal_branches"][1]["basis_evidence_ids"] = ["CALC_before"]
                    elif variant == "same_source":
                        data["evidence"][-1]["source_ref"] = data["evidence"][-2]["source_ref"]
                    elif variant == "interpretation":
                        for evidence in data["evidence"][-2:]:
                            evidence["kind"] = "traditional_interpretation"
                    else:
                        for evidence in data["evidence"][-2:]:
                            evidence["status"] = "unknown"
                before = deepcopy(data)
                result = check_record(data)
                self.assertTrue(result["record_valid"])
                self.assertEqual(result["submission_status"], "submitted")
                self.assertEqual(result["primary"], "A")
                self.assertEqual(result["effective_status"], "unresolved")
                self.assertEqual(result["primary_ranking_status"], "unsupported")
                self.assertEqual(result["review_completion_status"], "needs_review")
                self.assertEqual([x["status"] for x in result["temporal_review_statuses"]], ["needs_review", "needs_review"])
                self.assertIn("missing_branch_specific_basis", codes(result))
                self.assertIn("copied_temporal_comparison", {x["code"] for x in result["quality_warnings"]})
                self.assertIn("不能为通过检查编造证据", " ".join(result["review_actions"]))
                self.assertIn("回到各时间分支的实际计算", render_summary(data))
                self.assertEqual(data, before)

    def test_missing_branch_basis_is_not_cured_by_rephrasing_and_bad_ids_are_invalid(self):
        data = ranked_record()
        data["expected_temporal_branch_ids"] = ["before", "after"]
        data["temporal_branches"] = [
            {"id": identifier, "primary": "A", "ranking": deepcopy(data["ranking"]),
             "ranking_reason": "这是分支 " + identifier + " 的排序文字。"} for identifier in ("before", "after")]
        result = check_record(data)
        self.assertIn("missing_branch_specific_basis", codes(result))
        self.assertEqual(result["submission_status"], "submitted")
        self.assertNotIn("copied_temporal_comparison", {x["code"] for x in result["quality_warnings"]})
        data["temporal_branches"][0]["basis_evidence_ids"] = ["absent"]
        self.assertFalse(check_record(data)["record_valid"])

    def test_lower_tier_tie_does_not_create_a_unique_strongest_alternative(self):
        data = ranked_record()
        data["ranking"] = [["A"], ["B", "C"]]
        result = check_record(data)
        self.assertEqual(result["primary_ranking_status"], "relative_basis_declared")
        self.assertEqual(result["alternative_role"], "tied_comparator")
        self.assertIn("并列对照（原记录）：B", render_summary(data))
        self.assertNotIn("最强备选", render_summary(data))

    def test_exact_repeated_comparisons_warn_without_blocking_or_changing_evidence_status(self):
        data = ranked_record()
        for review in data["candidate_reviews"]:
            review["comparison"] = "同一段非空总述；相同也可能是实际并列结论。"
        result = check_record(data)
        self.assertEqual(result["effective_status"], "relative_basis_declared")
        self.assertEqual(result["submission_status"], "submitted")
        self.assertEqual(result["quality_warnings"][0]["code"], "repeated_candidate_comparison")
        self.assertEqual(result["quality_warnings"][0]["candidate_ids"], ["A", "B", "C"])
        self.assertEqual(result["quality_warnings"][0]["match_type"], "exact")
        for review in data["candidate_reviews"]:
            review["comparison"] = "  "
        self.assertFalse(check_record(data)["quality_warnings"])

    def test_different_prefixes_on_dominant_copied_tail_locate_reviews_in_all_versions(self):
        for version in (1, 2, 3):
            with self.subTest(version=version):
                data = ranked_record() if version == 3 else symmetric_record(version)
                for review in data["candidate_reviews"][:2]:
                    review["comparison"] = "候选" + review["id"] + "：" + SYNTHETIC_COMPARISON_OVERVIEW
                before = deepcopy(data)
                result = check_record(data)
                self.assertTrue(result["record_valid"])
                self.assertEqual(result["effective_status"], "relative_basis_declared")
                self.assertEqual(result["submission_status"], "submitted")
                self.assertEqual(result["primary"], "A")
                self.assertEqual(len(result["quality_warnings"]), 1)
                warning = result["quality_warnings"][0]
                self.assertEqual(warning["code"], "repeated_candidate_comparison")
                self.assertEqual(warning["match_type"], "dominant_shared_suffix")
                self.assertEqual(warning["candidate_ids"], ["A", "B"])
                self.assertEqual(warning["comparison_paths"], [
                    "$.candidate_reviews[0].comparison", "$.candidate_reviews[1].comparison"])
                self.assertGreaterEqual(warning["shared_suffix_chars"], len(SYNTHETIC_COMPARISON_OVERVIEW))
                self.assertEqual(result["review_completion_status"], "needs_review" if version == 3 else "not_checked")
                self.assertIn("comparison_paths", " ".join(result["review_actions"]))
                self.assertIn("候选 A、B 的比较文字共用占主体的相同长尾", render_summary(data))
                self.assertEqual(data, before)

    def test_different_comparisons_with_a_nondominant_shared_tail_do_not_warn(self):
        data = ranked_record()
        distinct_comparisons = [
            "甲的合成条件对应取得阶段，与乙的准备阶段不同；这项差异只涉及当前目标，不能补齐其余细节。",
            "乙的合成条件仅对应准备阶段，与甲的取得条件不同；另有必要前提尚未确定，须保留其限制。",
            "丙的合成条件对应后续维持阶段，与甲的取得阶段不同；需要分别查明先前状态，暂不作升级。",
        ]
        for review, comparison in zip(data["candidate_reviews"], distinct_comparisons):
            review["comparison"] = comparison * 4 + SYNTHETIC_COMPARISON_OVERVIEW
        self.assertFalse(check_record(data)["quality_warnings"])

    def test_short_shared_phrases_do_not_warn_even_when_they_dominate(self):
        data = ranked_record()
        for review in data["candidate_reviews"]:
            review["comparison"] = review["id"] + "：现有资料无法区分，暂保留未知。"
        self.assertFalse(check_record(data)["quality_warnings"])

    def test_all_unknown_with_copied_overview_still_submits_without_inventing_evidence(self):
        data = tied_record()
        for review in data["candidate_reviews"]:
            review["comparison"] = "候选" + review["id"] + "：" + SYNTHETIC_COMPARISON_OVERVIEW
        before = deepcopy(data)
        result = check_record(data)
        self.assertTrue(result["record_valid"])
        self.assertEqual(result["submission_status"], "submitted")
        self.assertEqual(result["effective_status"], "unresolved")
        self.assertEqual(result["primary"], "A")
        self.assertEqual(result["primary_ranking_status"], "tied")
        self.assertEqual(result["review_completion_status"], "needs_review")
        self.assertEqual({item["code"] for item in result["quality_warnings"]},
                         {"repeated_candidate_comparison", "empty_candidate_basis"})
        self.assertEqual(result["quality_warnings"][0]["candidate_ids"], ["A", "B", "C"])
        self.assertEqual(len(result["unknown_claims"]), 3)
        self.assertNotIn("primary_contradicted", codes(result))
        self.assertEqual(data, before)

    def test_summary_titles_use_fields_preserve_prose_and_never_correct_choice(self):
        data = ranked_record()
        data["candidate_reviews"][0]["comparison"] = "保留原文：这里可能仍有旧对照名称。"
        data["ranking"] = [["B"], ["A"], ["C"]]
        before = deepcopy(data)
        rendered = render_summary(data)
        self.assertIn("首选（原记录）：A", rendered)
        self.assertIn("声明排名：B > A > C", rendered)
        self.assertIn("候选 A；主要对照：B", rendered)
        self.assertIn(data["candidate_reviews"][0]["comparison"], rendered)
        self.assertLess(rendered.index("## 候选 B"), rendered.index("## 候选 A"))
        self.assertEqual(data, before)

    def test_markdown_cli_uses_separate_paths_and_protects_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output, markdown = root / "input.json", root / "check.json", root / "summary.md"
            original = json.dumps(ranked_record(), ensure_ascii=False)
            source.write_text(original, encoding="utf-8")
            command = [sys.executable, str(ROOT / "scripts/decision_record.py"), "--input", str(source),
                       "--output", str(output), "--markdown"]
            proc = subprocess.run(command + [str(markdown)], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("候选 A；主要对照：B", markdown.read_text(encoding="utf-8"))
            symlink, hardlink = root / "source-link.md", root / "output-link.md"
            symlink.symlink_to(source)
            os.link(output, hardlink)
            before_output = output.read_text(encoding="utf-8")
            for protected in (source, output, symlink, hardlink):
                proc = subprocess.run(command + [str(protected)], capture_output=True, text=True)
                self.assertEqual(proc.returncode, 2)
                self.assertIn("拒绝覆盖", proc.stderr)
                self.assertEqual(source.read_text(encoding="utf-8"), original)
                self.assertEqual(output.read_text(encoding="utf-8"), before_output)


if __name__ == "__main__":
    unittest.main()

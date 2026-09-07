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

from decision_record import check_record


ROOT = Path(__file__).resolve().parents[1]


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
                self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["effective_status"], expected_status)

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


if __name__ == "__main__":
    unittest.main()

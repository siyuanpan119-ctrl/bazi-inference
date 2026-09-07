"""Record consistency tests using synthetic data; not prediction-validity tests."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
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

"""Synthetic protocol regressions, not tests of divination accuracy."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from trial_preflight import ARMS, TRACE_FIELDS, preflight, verify_manifest, write_new_manifest


class TrialPreflightTests(unittest.TestCase):
    def fixture(self, root):
        root = Path(root)
        plan = {"trial_id": "synthetic-protocol", "expected_question_count": 1,
                "question_persons": {"q-demo": "person-heldout"},
                "development_person_ids": ["person-development"],
                "evaluation_person_ids": ["person-heldout"],
                "scoring_policy": {"primary_only": True, "retain_all_questions": True,
                                   "report_coverage": True},
                "fusion_policy_file": "fusion.md", "arms": {}}
        (root / "fusion.md").write_text("Synthetic fixed policy: disagreement retains the Bazi primary.", encoding="utf-8")
        row = {"question_id": "q-demo", "seen_answers": False,
               "candidates": [{"id": choice, "atoms": [{"subject": "synthetic person",
                    "domain": "career", "action": "synthetic career option " + choice,
                    "year": None}]} for choice in "AB"],
               "evidence": [{"id": "e-demo", "claim": "Synthetic conditional relation only",
                             "source_ref": "synthetic chart artifact"}],
               "trace": {field: "Synthetic explanation of " + field for field in TRACE_FIELDS},
               "selection": {"primary": "A"}}
        for name in ARMS:
            directory = root / name
            directory.mkdir()
            (directory / "SKILL.md").write_text("Synthetic instructions " + name, encoding="utf-8")
            current = copy.deepcopy(row)
            if name.endswith("ziwei"):
                current.update(ziwei_status="ready", ziwei_raw_choice="B")
            (directory / "records.json").write_text(json.dumps([current]), encoding="utf-8")
            plan["arms"][name] = {"skill_root": name, "records_file": name + "/records.json",
                                  "host": {"model_id": "synthetic-model", "model_version": "test-v1",
                                           "reasoning_effort": "high", "instructions_version": "test-host-v1"}}
        (root / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        return plan

    def change_row(self, root, change):
        path = Path(root) / ARMS[0] / "records.json"
        rows = json.loads(path.read_text())
        change(rows[0])
        path.write_text(json.dumps(rows), encoding="utf-8")

    def test_empty_evidence_keeps_raw_scoring_but_fails_readiness(self):
        with tempfile.TemporaryDirectory() as root:
            self.fixture(root)
            self.change_row(root, lambda row: row.update(evidence=[]))
            report = preflight("plan.json", root)
            arm = report["arms"][ARMS[0]]
            self.assertFalse(arm["process_complete"])
            self.assertTrue(arm["raw_accuracy_scoring_possible"])
            self.assertTrue(any("empty_evidence" in issue for issue in arm["issues"]))

    def test_placeholder_atoms_and_trace_do_not_count_as_complete(self):
        with tempfile.TemporaryDirectory() as root:
            self.fixture(root)
            def change(row):
                row["candidates"][0]["atoms"][0]["action"] = "原题选项A"
                row["trace"]["differentiator"] = "待填写"
            self.change_row(root, change)
            report = preflight("plan.json", root)
            issues = report["arms"][ARMS[0]]["issues"]
            self.assertTrue(any("candidate_atom_incomplete" in issue for issue in issues))
            self.assertTrue(any("differentiator" in issue for issue in issues))

    def test_changed_skill_file_invalidates_actual_snapshot(self):
        with tempfile.TemporaryDirectory() as root:
            self.fixture(root)
            report = preflight("plan.json", root)
            self.assertTrue(report["comparable_protocol_declared"])
            self.assertTrue(verify_manifest(report, root)["snapshot_matches"])
            (Path(root) / ARMS[1] / "SKILL.md").write_text("Changed instructions", encoding="utf-8")
            self.assertFalse(verify_manifest(report, root)["snapshot_matches"])

    def test_cache_and_private_files_are_not_hashed(self):
        with tempfile.TemporaryDirectory() as root:
            self.fixture(root)
            report = preflight("plan.json", root)
            for folder in ("__pycache__", "node_modules", ".git", "private", "trial-private-data",
                           "registry", "answers", "predictions", "submissions", "reviews",
                           "reports", "local-data", "private-data"):
                path = Path(root) / ARMS[0] / folder
                path.mkdir()
                (path / "ignored.txt").write_text("Excluded content", encoding="utf-8")
            self.assertTrue(verify_manifest(report, root)["snapshot_matches"])

    def test_real_short_atoms_and_existing_event_evidence_are_accepted(self):
        with tempfile.TemporaryDirectory() as root:
            self.fixture(root)
            for name in ARMS:
                path = Path(root) / name / "records.json"
                rows = json.loads(path.read_text())
                rows[0]["candidates"][0]["atoms"][0].update(subject="命主", action="结婚")
                rows[0]["evidence"] = [
                    {"id": "r1", "kind": "computed_relation", "source_group": "synthetic-clash",
                     "statement": "日支受冲"},
                    {"id": "h1", "kind": "traditional_hypothesis", "statement": "关系变化候选解释",
                     "basis_ids": ["r1"], "warrant": "仍然不能区分登记与一般生活安排"}]
                path.write_text(json.dumps(rows), encoding="utf-8")
            self.assertTrue(preflight("plan.json", root)["comparable_protocol_declared"])

    def test_malformed_host_and_selection_produce_issues(self):
        with tempfile.TemporaryDirectory() as root:
            plan = self.fixture(root)
            plan["arms"][ARMS[0]]["host"] = None
            (Path(root) / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
            self.change_row(root, lambda row: row.update(selection=None))
            report = preflight("plan.json", root)
            self.assertFalse(report["comparable_protocol_declared"])
            self.assertFalse(report["arms"][ARMS[0]]["raw_accuracy_scoring_possible"])

    def test_unknown_host_or_person_leakage_is_not_comparable(self):
        with tempfile.TemporaryDirectory() as root:
            plan = self.fixture(root)
            plan["arms"][ARMS[0]]["host"]["model_version"] = "unknown"
            plan["development_person_ids"].append("person-heldout")
            (Path(root) / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
            report = preflight("plan.json", root)
            self.assertFalse(report["comparable_protocol_declared"])
            self.assertTrue(any("host_model" in issue for issue in report["issues"]))
            self.assertIn("person_holdout_missing_or_development_overlap", report["issues"])

    def test_absent_raw_ziwei_choice_fails_combined_arm(self):
        with tempfile.TemporaryDirectory() as root:
            self.fixture(root)
            path = Path(root) / ARMS[2] / "records.json"
            rows = json.loads(path.read_text())
            del rows[0]["ziwei_raw_choice"]
            path.write_text(json.dumps(rows), encoding="utf-8")
            report = preflight("plan.json", root)
            self.assertFalse(report["arms"][ARMS[2]]["process_complete"])

    def test_manifest_writer_never_overwrites(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "manifest.json"
            write_new_manifest({"original": True}, path)
            with self.assertRaises(FileExistsError):
                write_new_manifest({"original": False}, path)
            self.assertEqual(json.loads(path.read_text()), {"original": True})


if __name__ == "__main__":
    unittest.main()

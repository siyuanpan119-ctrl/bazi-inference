"""Synthetic protocol regressions, not tests of divination accuracy."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from trial_preflight import (ARMS, TRACE_FIELDS, PAIRED_SCHEMA, file_manifest,
                             skill_manifest, preflight, verify_manifest, write_new_manifest)
from test_event_rules import example_record


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

    def paired_fixture(self, root):
        root = Path(root)
        question = {"question_id": "synthetic-q", "person_id": "synthetic-p",
                    "stem": "合成流程测试，不是真实命例", "observation_year": 2030,
                    "options": {"A": "合成选项甲", "B": "合成选项乙"}}
        (root / "questions.json").write_text(json.dumps({"questions": [question]}))
        (root / "fusion.md").write_text("Synthetic fixed change package only.")
        plan = {"schema_version": PAIRED_SCHEMA, "status": "predictions_frozen",
                "trial_id": "synthetic-paired", "questions_file": "questions.json",
                "expected_question_count": 1, "question_persons": {"synthetic-q": "synthetic-p"},
                "development_person_ids": [], "evaluation_person_ids": ["synthetic-p"],
                "context_policy": "isolated_no_keys_no_other_arms",
                "repetitions": 1, "stem_only_control": False, "fusion_policy_file": "fusion.md",
                "scoring_policy": {"primary_only": True, "retain_all_questions": True,
                                   "report_coverage": True}, "arms": {}}
        for name in ("old", "new"):
            skill = root / "snapshots" / name
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("Synthetic instructions " + name)
            output = root / "outputs" / name
            output.mkdir(parents=True)
            record = example_record()
            record.update(question_id=question["question_id"], original_stem=question["stem"],
                          observation_year=question["observation_year"],
                          trace={field: "Synthetic trace " + field for field in TRACE_FIELDS})
            record["selection"]["unresolved"] = True
            for candidate in record["candidates"]:
                candidate["text"] = question["options"][candidate["id"]]
            (output / "records.json").write_text(json.dumps([record]))
            plan["arms"][name] = {"skill_root": "snapshots/" + name,
                "records_file": "outputs/" + name + "/records.json",
                "input_sha256": file_manifest(root / "questions.json", root)["sha256"],
                "skill_sha256": skill_manifest(skill)["sha256"],
                "host": {"model_id": "synthetic", "model_version": "test-v1",
                         "reasoning_effort": "high", "instructions_version": "test-host-v1",
                         "sampling": {"temperature": 0}, "max_output_tokens": 1000}}
        (root / "plan.json").write_text(json.dumps(plan))
        return plan

    def test_paired_known_settings_and_frozen_decisions(self):
        with tempfile.TemporaryDirectory() as directory:
            self.paired_fixture(directory)
            report = preflight("plan.json", directory)
            self.assertTrue(report["comparable_protocol_declared"])
            self.assertTrue(verify_manifest(report, directory)["snapshot_matches"])
            self.assertEqual(report["arms"]["old"]["decision_counts"]["unresolved"], 1)
            self.assertEqual(report["arms"]["old"]["decision_counts"]["forced_guess"], 1)

    def test_paired_unknown_host_is_descriptive_not_blocked_or_fabricated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self.paired_fixture(root)
            for arm in plan["arms"].values():
                arm["host"].update(model_version="unknown", sampling="unknown")
            (root / "plan.json").write_text(json.dumps(plan))
            report = preflight("plan.json", root)
            self.assertEqual(report["status"], "descriptive_ready")
            self.assertTrue(report["descriptive_scoring_ready"])
            self.assertFalse(report["comparable_protocol_declared"])
            self.assertEqual(report["snapshot"]["arms"]["old"]["host"]["sampling"], "unknown")

    def test_paired_changed_question_year_options_or_missing_markers_fails(self):
        for field in ("original_stem", "observation_year", "text", "backup", "unresolved"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.paired_fixture(root)
                path = root / "outputs/old/records.json"
                records = json.loads(path.read_text())
                if field in {"backup", "unresolved"}:
                    del records[0]["selection"][field]
                elif field == "text":
                    records[0]["candidates"][0][field] = "changed option"
                else:
                    records[0][field] = 2031 if field == "observation_year" else "changed stem"
                path.write_text(json.dumps(records))
                report = preflight("plan.json", root)
                self.assertFalse(report["descriptive_scoring_ready"])

    def test_paired_input_and_skill_hashes_are_verified(self):
        for field in ("input_sha256", "skill_sha256"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                plan = self.paired_fixture(root)
                plan["arms"]["old"][field] = "not-the-actual-hash"
                (root / "plan.json").write_text(json.dumps(plan))
                self.assertFalse(preflight("plan.json", root)["descriptive_scoring_ready"])

    def test_paired_rejects_answer_fields_and_shared_output_directory(self):
        for problem in ("leak", "directory"):
            with self.subTest(problem=problem), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                plan = self.paired_fixture(root)
                if problem == "leak":
                    plan["metadata"] = {"answer_key": "A"}
                else:
                    plan["arms"]["new"]["records_file"] = plan["arms"]["old"]["records_file"]
                (root / "plan.json").write_text(json.dumps(plan))
                with self.assertRaises(ValueError):
                    preflight("plan.json", root)

    def test_paired_rejects_nonobject_questions_cleanly(self):
        for question in (None, 42, "synthetic-invalid", []):
            with self.subTest(question=question), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.paired_fixture(root)
                (root / "questions.json").write_text(json.dumps({"questions": [question]}))
                with self.assertRaisesRegex(ValueError, "Each question must be a JSON object"):
                    preflight("plan.json", root)

    def test_paired_rejects_shared_or_nested_skill_snapshots(self):
        for skill_root in ("snapshots/old", "snapshots/old/nested", "snapshots"):
            with self.subTest(skill_root=skill_root), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                plan = self.paired_fixture(root)
                plan["arms"]["new"]["skill_root"] = skill_root
                (root / "plan.json").write_text(json.dumps(plan))
                with self.assertRaisesRegex(ValueError, "distinct, non-nested"):
                    preflight("plan.json", root)

    def test_checked_in_next_plan_truthfully_waits_for_questions(self):
        root = Path(__file__).resolve().parents[1]
        report = preflight("assets/next-trial.json", root)
        self.assertEqual(report["status"], "awaiting_questions")
        self.assertFalse(report["descriptive_scoring_ready"])
        self.assertFalse(report["prediction_accuracy_validated"])
        self.assertEqual(set(report["snapshot"]), {"plan"})


if __name__ == "__main__":
    unittest.main()

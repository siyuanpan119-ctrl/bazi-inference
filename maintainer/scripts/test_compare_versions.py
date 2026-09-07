import copy
from pathlib import Path
import tempfile
import unittest

from benchmark import freeze_batch, register_receipt, score_batch
from compare_versions import compare_versions
from event_rules import AuditError
from test_event_rules import example_record


class PairedVersionTests(unittest.TestCase):
    def make_pair(self, tmp, *, hindsight=False, receipt=False, experiment=False,
                  mismatch=None, descriptive_preflight=False):
        p = Path(tmp)
        registry = p/"registry"
        paths = []
        for arm in ("old", "new"):
            records = [example_record(), example_record()]
            for i, record in enumerate(records):
                record["question_id"] = f"q{i+1}"
                record["original_stem"] = f"Synthetic question {i+1}"
                record["observation_year"] = 2030
                if hindsight:
                    record.update(mode="hindsight_review", seen_answers=True)
            if arm == "old":
                records[0]["selection"].update(primary="A", backup="B")
            else:
                records[1]["selection"].update(primary=None, backup=None, status="abstain")
            persons = {"q1":"p1", "q2":"p2"}
            keys = {"q1":"B", "q2":"B"}
            if arm == "new":
                if mismatch == "persons": persons["q2"] = "different-person"
                if mismatch == "keys": keys["q1"] = "A"
                if mismatch == "options": records[0]["candidates"][0]["atoms"][0]["detail"] = "changed question meaning"
                if mismatch == "eligible": records[0].update(mode="hindsight_review", seen_answers=True)
                if mismatch == "year": records[0]["observation_year"] = 2031
                if mismatch == "stem": records[0]["original_stem"] = "A different synthetic question"
                if mismatch == "missing_year": records[0].pop("observation_year")
            plan = None
            if experiment:
                plan = {"experiment_id":"synthetic-comparison", "training_person_ids":[],
                        "person_provenance":{v:"new_person_no_answers_seen" for v in persons.values()}}
                if descriptive_preflight:
                    plan["preflight_comparable_protocol_declared"] = False
            frozen, score = p/(arm+".json"), p/(arm+"-score.json")
            freeze_batch("synthetic-"+arm, arm, records, persons, ["q1","q2"], frozen,
                         registry_dir=registry, rule_snapshot={"version":arm,"rules":[]}, evaluation_plan=plan)
            if receipt:
                register_receipt(registry, "synthetic-"+arm, "synthetic external reference "+arm)
            score_batch(frozen, keys, score, registry_dir=registry)
            paths.extend([frozen, score])
        return paths, registry

    def test_paired_changes_keep_abstentions_in_denominator(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths, registry = self.make_pair(tmp)
            r = compare_versions(*paths, registry)
            self.assertEqual(r["n01_old_not_correct_new_correct"], 1)
            self.assertEqual(r["n10_old_correct_new_not_correct"], 1)
            self.assertEqual(r["full_denominator_accuracy_delta"], 0)
            self.assertEqual(r["coverage_delta"], -.5)
            self.assertEqual(r["by_person"]["p1"]["correctness_delta"], 1)
            self.assertEqual(r["by_person"]["p2"]["correctness_delta"], -1)
            self.assertEqual(r["mode"], "nonprospective_descriptive")
            self.assertEqual(r["by_decision_status_eligible"]["old"]["forced_guess"]["questions"], 2)
            self.assertEqual(r["by_decision_status_eligible"]["new"]["abstain"]["questions"], 1)
            self.assertEqual(r["unresolved_marker_missing_eligible"], {"old": 2, "new": 2})

    def test_same_difficulty_and_eligibility_are_required(self):
        for field in ("persons", "keys", "options", "eligible", "year", "stem", "missing_year"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                paths, registry = self.make_pair(tmp, mismatch=field)
                with self.assertRaises(AuditError):
                    compare_versions(*paths, registry)

    def test_hindsight_is_descriptive_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths, registry = self.make_pair(tmp, hindsight=True, receipt=True, experiment=True)
            r = compare_versions(*paths, registry, external_receipts_checked=True)
            self.assertEqual(r["mode"], "nonprospective_descriptive")
            self.assertEqual(r["eligible_questions"], 0)
            self.assertIsNone(r["full_denominator_accuracy_delta"])
            self.assertEqual(r["descriptive_all_rows_including_hindsight"]["old"]["questions"], 2)
            self.assertFalse(r["accuracy_improvement_established"])

    def test_declared_prospective_comparison_does_not_claim_significance(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths, registry = self.make_pair(tmp, receipt=True, experiment=True)
            r = compare_versions(*paths, registry, external_receipts_checked=True)
            self.assertEqual(r["mode"], "prospective_design_declared")
            self.assertTrue(r["comparison_has_external_receipts_checked"])
            self.assertFalse(r["statistical_significance_assessed"])
            self.assertFalse(r["accuracy_improvement_established"])

    def test_receipts_without_external_check_are_not_prospective(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths, registry = self.make_pair(tmp, receipt=True, experiment=True)
            r = compare_versions(*paths, registry)
            self.assertEqual(r["mode"], "nonprospective_descriptive")
            self.assertFalse(r["comparison_has_external_receipts_checked"])

    def test_descriptive_preflight_limit_survives_external_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths, registry = self.make_pair(tmp, receipt=True, experiment=True,
                                             descriptive_preflight=True)
            result = compare_versions(*paths, registry, external_receipts_checked=True)
            self.assertEqual(result["mode"], "nonprospective_descriptive")
            self.assertTrue(any("preflight" in reason for reason in result["nonprospective_reasons"]))

    def test_same_submission_cannot_be_compared_to_itself(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths, registry = self.make_pair(tmp)
            with self.assertRaisesRegex(AuditError, "distinct"):
                compare_versions(paths[0], paths[1], paths[0], paths[1], registry)


if __name__ == "__main__":
    unittest.main()

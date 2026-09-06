import copy
import json
from pathlib import Path
import tempfile
import unittest

from benchmark import (freeze_batch, score_batch, register_receipt, load_json,
                       validate_person_split, _batch_path)
from event_rules import AuditError
from test_event_rules import example_record


class WholeBatchTests(unittest.TestCase):
    def records(self):
        a, b = example_record(), example_record()
        a["question_id"], b["question_id"] = "TQ1", "TQ2"
        b["selection"].update(primary=None, backup=None, status="abstain")
        return [a, b]

    def freeze(self, path, records=None, registry=None):
        return freeze_batch("synthetic-batch", "v1", records or self.records(),
                            {"TQ1": "person-one", "TQ2": "person-one"},
                            ["TQ1", "TQ2"], path,
                            registry_dir=registry or Path(path).parent / "registry",
                            rule_snapshot={"version": "v1", "rules": []})

    def score(self, frozen, keys, out, registry=None):
        return score_batch(frozen, keys, out,
                           registry_dir=registry or Path(frozen).parent / "registry")

    def test_abstention_stays_in_full_denominator(self):
        with tempfile.TemporaryDirectory() as tmp:
            frozen, scored = Path(tmp)/"submission.json", Path(tmp)/"score.json"
            self.freeze(frozen)
            before = frozen.read_bytes()
            result = self.score(frozen, {"TQ1": "B", "TQ2": "A"}, scored)
            self.assertEqual(result["eligible_score"]["accuracy_on_full_denominator"], .5)
            self.assertEqual(result["eligible_score"]["accuracy_among_answered"], 1)
            self.assertEqual(result["eligible_score"]["coverage"], .5)
            self.assertEqual(len(result["by_person"]), 1)
            self.assertEqual(before, frozen.read_bytes())

    def test_duplicate_question_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = self.records()
            r[1]["question_id"] = "TQ1"
            with self.assertRaisesRegex(AuditError, "Duplicate"):
                self.freeze(Path(tmp)/"submission.json", r)

    def test_cannot_drop_an_unfavorable_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            frozen = Path(tmp)/"submission.json"
            self.freeze(frozen)
            with self.assertRaisesRegex(AuditError, "every frozen question"):
                self.score(frozen, {"TQ1": "B"}, Path(tmp)/"score.json")

    def test_immutable_batch_and_separate_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            frozen, score = Path(tmp)/"submission.json", Path(tmp)/"score.json"
            self.freeze(frozen)
            with self.assertRaises(FileExistsError):
                self.freeze(frozen)
            self.score(frozen, {"TQ1": "A", "TQ2": "B"}, score)
            with self.assertRaises(FileExistsError):
                self.score(frozen, {"TQ1": "A", "TQ2": "B"}, score)

    def test_same_batch_different_output_path_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.freeze(Path(tmp)/"first.json")
            with self.assertRaisesRegex(AuditError, "already registered"):
                self.freeze(Path(tmp)/"second.json")
            self.assertFalse((Path(tmp)/"second.json").exists())

    def test_score_cannot_choose_a_second_key_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            frozen = Path(tmp)/"submission.json"
            self.freeze(frozen)
            self.score(frozen, {"TQ1": "A", "TQ2": "B"}, Path(tmp)/"score-one.json")
            with self.assertRaisesRegex(AuditError, "already scored"):
                self.score(frozen, {"TQ1": "B", "TQ2": "B"}, Path(tmp)/"score-two.json")

    def test_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            frozen = Path(tmp)/"submission.json"
            self.freeze(frozen)
            data = load_json(frozen)
            data["body"]["records"][0]["selection"]["primary"] = "A"
            frozen.write_text(json.dumps(data))
            with self.assertRaisesRegex(AuditError, "hash mismatch"):
                self.score(frozen, {"TQ1":"A", "TQ2":"B"}, Path(tmp)/"score.json")

    def test_prompt_revealed_answer_excluded_from_batch_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            records = self.records()
            records[0]["evidence"].append({
                "id": "given", "kind": "prompt_fact", "source_group": "question-stem",
                "source_role": "question_stem", "statement": "The prompt states the full event.",
                "prompt_excerpt": "Synthetic statement: the person divorced in 2021.",
                "direction": "support", "target_atoms": ["B.divorced"]})
            frozen, score = Path(tmp)/"submission.json", Path(tmp)/"score.json"
            self.freeze(frozen, records)
            result = self.score(frozen, {"TQ1": "B", "TQ2": "A"}, score)
            self.assertEqual(result["excluded_question_count"], 1)
            self.assertEqual(result["eligible_score"]["questions"], 1)

    def test_rule_snapshot_must_match_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(AuditError, "matching rule snapshot"):
                freeze_batch("test", "v2", self.records(),
                             {"TQ1":"p1", "TQ2":"p1"}, ["TQ1","TQ2"],
                             Path(tmp)/"out.json", registry_dir=Path(tmp)/"registry",
                             rule_snapshot={"version":"v1"})

    def test_same_person_cannot_cross_partitions(self):
        with self.assertRaisesRegex(AuditError, "one person"):
            validate_person_split({"q1":"p1", "q2":"p1"},
                                  {"q1":"training", "q2":"test"})
        self.assertEqual(validate_person_split({"q1":"p1", "q2":"p2"},
                                               {"q1":"training", "q2":"test"}),
                         {"p1":"training", "p2":"test"})

    def test_receipt_is_immutable_and_cannot_be_added_after_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = Path(tmp)/"registry"
            frozen = Path(tmp)/"submission.json"
            self.freeze(frozen)
            register_receipt(registry, "synthetic-batch", "synthetic external record")
            with self.assertRaises(FileExistsError):
                register_receipt(registry, "synthetic-batch", "another reference")
            result = self.score(frozen, {"TQ1":"A", "TQ2":"B"}, Path(tmp)/"score.json")
            self.assertFalse(result["external_precommit_receipt"]["external_reference_verified_by_program"])
            with self.assertRaisesRegex(AuditError, "after scoring"):
                register_receipt(registry, "synthetic-batch", "late reference")

    def test_duplicate_json_answer_keys_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"keys.json"
            path.write_text('{"TQ1":"A","TQ1":"B"}')
            with self.assertRaisesRegex(AuditError, "Duplicate JSON key"):
                load_json(path)

    def test_unregistered_copy_is_not_scored(self):
        with tempfile.TemporaryDirectory() as tmp:
            frozen = Path(tmp)/"submission.json"
            self.freeze(frozen)
            with self.assertRaisesRegex(AuditError, "first local registration"):
                self.score(frozen, {"TQ1":"A", "TQ2":"B"}, Path(tmp)/"out.json",
                           registry=Path(tmp)/"other-registry")


if __name__ == "__main__":
    unittest.main()

"""Behavioral tests for answer isolation and the event inference boundary."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from event_rules import AuditError, RULE_DECLARATION, SCHEMA_VERSION, audit_record, freeze_record, score_frozen


def example_record():
    return {
        "schema_version": SCHEMA_VERSION,
        "question_id": "synthetic-marriage-status",
        "mode": "blind",
        "seen_answers": False,
        "terminology": copy.deepcopy(RULE_DECLARATION),
        "assumptions": ["Synthetic contract test; this is not a person's chart."],
        "candidates": [
            {"id": "A", "atoms": [{"id": "A.never_married", "subject": "命主", "domain": "marriage", "action": "never_married", "year": None, "detail": None}]},
            {"id": "B", "atoms": [{"id": "B.divorced", "subject": "命主", "domain": "marriage", "action": "divorced", "year": 2021, "detail": None}]},
        ],
        "evidence": [
            {"id": "r1", "kind": "computed_relation", "source_group": "day-branch-clash", "statement": "日支受冲", "direction": "context", "target_atoms": []},
            {"id": "r2", "kind": "computed_relation", "source_group": "day-branch-clash", "statement": "夫妻宫受冲，和 r1 为同一底层关系", "direction": "context", "target_atoms": []},
            {"id": "h1", "kind": "traditional_hypothesis", "statement": "解释者提出离婚假设", "direction": "support", "target_atoms": ["B.divorced"], "basis_ids": ["r1"], "warrant": "传统关联，不能区分分手与法律离婚", "validation_status": "unvalidated"},
            {"id": "h2", "kind": "traditional_hypothesis", "statement": "同源的重复离婚假设", "direction": "support", "target_atoms": ["B.divorced"], "basis_ids": ["r2"], "warrant": "同一冲关系换名，不增加独立证据", "validation_status": "unvalidated"},
        ],
        "selection": {"primary": "B", "backup": "A", "status": "forced_guess", "rationale": "Only a forced guess; legal marriage history is missing."},
    }


class EventAuditTests(unittest.TestCase):
    def test_same_source_relationship_is_counted_once(self):
        result = audit_record(example_record())
        second = result["candidate_audits"][1]
        self.assertEqual(second["distinct_source_group_count"], 1)
        self.assertEqual(second["support_source_groups"], ["day-branch-clash"])

    def test_unknown_is_not_counterevidence(self):
        first = audit_record(example_record())["candidate_audits"][0]
        self.assertEqual(first["status"], "unidentifiable")
        self.assertEqual(first["atoms"][0]["counterevidence_ids"], [])
        self.assertTrue(first["atoms"][0]["missing_support"])

    def test_hypothesis_does_not_establish_marriage_history(self):
        second = audit_record(example_record())["candidate_audits"][1]
        self.assertEqual(second["status"], "unidentifiable")
        self.assertTrue(second["atoms"][0]["unresolved"])

    def test_computed_relation_cannot_directly_classify_event(self):
        record = example_record()
        record["evidence"][0]["direction"] = "support"
        record["evidence"][0]["target_atoms"] = ["B.divorced"]
        with self.assertRaisesRegex(AuditError, "cannot directly determine"):
            audit_record(record)

    def test_nested_answer_key_is_rejected(self):
        record = example_record()
        record["metadata"] = {"training": {"correct_answer": "A"}}
        with self.assertRaisesRegex(AuditError, "Answer-key field forbidden"):
            audit_record(record)

    def test_answer_seen_record_cannot_claim_blind(self):
        record = example_record()
        record["seen_answers"] = True
        with self.assertRaisesRegex(AuditError, "cannot be a blind"):
            audit_record(record)

    def test_hindsight_is_excluded_from_blind_scoring(self):
        record = example_record()
        record.update(mode="hindsight_review", seen_answers=True)
        with tempfile.TemporaryDirectory() as directory:
            frozen, scored = Path(directory) / "frozen.json", Path(directory) / "score.json"
            freeze_record(record, frozen)
            result = score_frozen(frozen, "B", scored)
            self.assertTrue(result["correct"])
            self.assertFalse(result["eligible_for_blind_scoring"])

    def test_revealed_key_does_not_change_frozen_interpretation(self):
        with tempfile.TemporaryDirectory() as directory:
            frozen, scored = Path(directory) / "frozen.json", Path(directory) / "score.json"
            digest = freeze_record(example_record(), frozen)
            before = frozen.read_bytes()
            result = score_frozen(frozen, "A", scored)
            self.assertFalse(result["correct"])
            self.assertEqual(result["prediction_sha256"], digest)
            self.assertEqual(frozen.read_bytes(), before)
            with self.assertRaises(FileExistsError):
                freeze_record(example_record(), frozen)

    def test_tampering_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            frozen, scored = Path(directory) / "frozen.json", Path(directory) / "score.json"
            freeze_record(example_record(), frozen)
            content = json.loads(frozen.read_text(encoding="utf-8"))
            content["body"]["record"]["selection"]["primary"] = "A"
            frozen.write_text(json.dumps(content), encoding="utf-8")
            with self.assertRaisesRegex(AuditError, "hash mismatch"):
                score_frozen(frozen, "A", scored)

    def test_circular_warrants_are_rejected(self):
        record = example_record()
        record["evidence"][2]["basis_ids"] = ["h2"]
        record["evidence"][3]["basis_ids"] = ["h1"]
        with self.assertRaisesRegex(AuditError, "Cyclic"):
            audit_record(record)

    def test_partial_prompt_fact_does_not_prove_a_composite_option(self):
        record = example_record()
        record["candidates"][1]["atoms"].append({"id": "B.child", "subject": "命主", "domain": "children", "action": "has_daughter", "year": None, "detail": None})
        record["evidence"].append({"id": "fact", "kind": "prompt_fact", "source_group": "given-divorce", "source_role": "question_stem", "statement": "题干明确 2021 年离婚", "prompt_excerpt": "命主于 2021 年离婚", "direction": "support", "target_atoms": ["B.divorced"]})
        result = audit_record(record)["candidate_audits"][1]
        self.assertEqual(result["status"], "unidentifiable")
        self.assertTrue(result["atoms"][1]["missing_support"])

    def test_generic_support_cannot_be_declared_certain(self):
        record = example_record()
        record["selection"]["status"] = "stated_in_prompt"
        with self.assertRaisesRegex(AuditError, "not fully stated"):
            audit_record(record)

    def test_user_terminology_cannot_be_redefined(self):
        record = example_record()
        record["terminology"]["用神"] = "凡是平衡命局的五行"
        with self.assertRaisesRegex(AuditError, "definitions separate"):
            audit_record(record)

    def test_option_text_is_not_a_hard_fact(self):
        record = example_record()
        record["evidence"].append({"id": "fact", "kind": "prompt_fact", "source_group": "option-B", "source_role": "candidate_option", "statement": "选项写 2021 年离婚", "prompt_excerpt": "命主于 2021 年离婚", "direction": "support", "target_atoms": ["B.divorced"]})
        with self.assertRaisesRegex(AuditError, "not a hard prompt fact"):
            audit_record(record)

    def test_hard_counterevidence_blocks_selected_candidate(self):
        record = example_record()
        record["evidence"].append({"id": "fact", "kind": "prompt_fact", "source_group": "given-never-married", "source_role": "question_stem", "statement": "题干明确未曾结婚", "prompt_excerpt": "命主从未结婚", "direction": "refute", "target_atoms": ["B.divorced"]})
        with self.assertRaisesRegex(AuditError, "contradicts a declared hard"):
            audit_record(record)

    def test_disclosed_candidate_excludes_blind_scoring_even_when_forced_guess(self):
        record = example_record()
        record["evidence"].append({"id": "fact", "kind": "prompt_fact", "source_group": "given-divorce", "source_role": "question_stem", "statement": "题干明确 2021 年离婚", "prompt_excerpt": "命主于 2021 年离婚", "direction": "support", "target_atoms": ["B.divorced"]})
        for status, primary in [("forced_guess", "B"), ("stated_in_prompt", "B"), ("forced_guess", "A"), ("abstain", None)]:
            with self.subTest(status=status, primary=primary):
                record["selection"].update(status=status, primary=primary, backup=None)
                result = audit_record(record)
                self.assertTrue(result["prompt_discloses_candidate"])
                self.assertFalse(result["eligible_for_blind_scoring"])

    def test_tuple_hidden_key_rejected_before_freeze(self):
        record = example_record()
        record["assumptions"] = [({"answer_key": "B"},)]
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "frozen.json"
            with self.assertRaisesRegex(AuditError, "JSON-native"):
                freeze_record(record, destination)
            self.assertFalse(destination.exists())

    def test_non_string_keys_rejected(self):
        record = example_record()
        record["metadata"] = {2: "would become a string on JSON reload"}
        with self.assertRaisesRegex(AuditError, "keys must be strings"):
            audit_record(record)

    def test_non_finite_numbers_rejected(self):
        for value in [float("nan"), float("inf"), -float("inf")]:
            with self.subTest(value=value):
                record = example_record()
                record["metadata"] = {"value": value}
                with self.assertRaisesRegex(AuditError, "Non-finite"):
                    audit_record(record)



if __name__ == "__main__":
    unittest.main()

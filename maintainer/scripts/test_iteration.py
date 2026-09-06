import copy
from pathlib import Path
import tempfile
import unittest

from benchmark import digest, create_new, register_receipt, score_batch
from event_rules import AuditError
from iteration import propose_rule, trial, promote_rule, validate_evaluation_plan
from test_event_rules import example_record


def proposal():
    return propose_rule({
        "id": "synthetic-test-rule", "title": "Synthetic contract rule",
        "source_ids": [], "prerequisites": ["A synthetic feature is present"],
        "structure_chain": ["Feature → tentative outcome"],
        "observable_claims": ["Choose the declared synthetic outcome"],
        "alternative_explanations": ["Other factors may explain the outcome"],
        "support": [], "counterexamples": [],
        "scope": {"domains": ["synthetic"], "conditions": [], "exclusions": []},
        "origin": "prospective_design",
    })


def fixture(card, hindsight=False):
    records = [example_record(), example_record()]
    records[0]["question_id"], records[1]["question_id"] = "sq1", "sq2"
    for record in records:
        record["applied_rule_ids"] = [card["id"]]
    if hindsight:
        for record in records:
            record.update(mode="hindsight_review", seen_answers=True)
    return {
        "batch_id": "synthetic-iteration-trial", "records": records,
        "question_persons": {"sq1":"new-person-a", "sq2":"new-person-b"},
        "expected_question_ids": ["sq1", "sq2"],
        "evaluation_plan": {
            "schema_version": "evaluation-plan-1.0", "rule_id": card["id"],
            "candidate_sha256": digest(card), "scope": copy.deepcopy(card["scope"]),
            "min_new_persons": 2, "min_questions": 2,
            "min_accuracy_full": 1.0, "min_coverage": 1.0,
            "training_person_ids": [],
            "person_provenance": {"new-person-a":"new_person_no_answers_seen",
                                  "new-person-b":"new_person_no_answers_seen"},
            "claim": "prospective_support_in_scope",
        },
    }


class IterationTests(unittest.TestCase):
    def trial_and_score(self, directory, request=None, card=None, keys=None, receipt=True):
        card = card or proposal()
        request = request or fixture(card)
        base = Path(directory)
        frozen, scored, registry = base/"submission.json", base/"score.json", base/"registry"
        rules = {"version":"synthetic-v1", "rules":[card]}
        trial(request, rules, frozen, registry)
        if receipt:
            register_receipt(registry, request["batch_id"], "synthetic external submission reference")
        score_batch(frozen, keys or {"sq1":"B", "sq2":"B"}, scored, registry_dir=registry)
        return card, frozen, scored, registry

    def test_review_cannot_self_promote(self):
        card = proposal()
        card.update(status="validated", evidence_status="scientifically_proven", origin="hindsight_review")
        reviewed = propose_rule(card)
        self.assertEqual(reviewed["status"], "proposed")
        self.assertEqual(reviewed["evidence_status"], "hindsight_supported")
        self.assertFalse(reviewed["universally_validated"])
        self.assertEqual(reviewed["support"], [])

    def test_new_blind_trial_passes_only_to_experimental_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            card, frozen, score, registry = self.trial_and_score(tmp)
            promoted = promote_rule(card, frozen, score, registry, external_receipt_verified=True)
            self.assertEqual(promoted["status"], "experimental")
            self.assertEqual(promoted["evidence_status"], "prospective_trial_supported")
            self.assertFalse(promoted["universally_validated"])
            self.assertEqual(card["status"], "proposed")

    def test_hindsight_cannot_be_promoted(self):
        with tempfile.TemporaryDirectory() as tmp:
            card = proposal()
            card, frozen, score, registry = self.trial_and_score(tmp, fixture(card, hindsight=True), card)
            with self.assertRaisesRegex(AuditError, "Hindsight"):
                promote_rule(card, frozen, score, registry, external_receipt_verified=True)

    def test_no_external_commitment_cannot_be_promoted(self):
        with tempfile.TemporaryDirectory() as tmp:
            card, frozen, score, registry = self.trial_and_score(tmp, receipt=False)
            with self.assertRaisesRegex(AuditError, "externally checked"):
                promote_rule(card, frozen, score, registry, external_receipt_verified=True)

    def test_unchecked_external_reference_cannot_be_promoted(self):
        with tempfile.TemporaryDirectory() as tmp:
            card, frozen, score, registry = self.trial_and_score(tmp)
            with self.assertRaisesRegex(AuditError, "externally checked"):
                promote_rule(card, frozen, score, registry)

    def test_changed_rule_after_answers_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            card, frozen, score, registry = self.trial_and_score(tmp)
            card["prerequisites"].append("New exception invented after reveal")
            with self.assertRaisesRegex(AuditError, "changed after"):
                promote_rule(card, frozen, score, registry, external_receipt_verified=True)

    def test_incorrect_prediction_fails_declared_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            card, frozen, score, registry = self.trial_and_score(tmp, keys={"sq1":"A", "sq2":"B"})
            with self.assertRaisesRegex(AuditError, "accuracy below"):
                promote_rule(card, frozen, score, registry, external_receipt_verified=True)

    def test_abstention_cannot_inflate_promotion_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            card = proposal()
            request = fixture(card)
            request["records"][0]["selection"].update(primary=None, backup=None, status="abstain")
            card, frozen, score, registry = self.trial_and_score(tmp, request, card)
            with self.assertRaisesRegex(AuditError, "accuracy below.*coverage below"):
                promote_rule(card, frozen, score, registry, external_receipt_verified=True)

    def test_training_person_cannot_be_relabeled_as_new(self):
        card = proposal()
        request = fixture(card)
        request["evaluation_plan"]["training_person_ids"] = ["new-person-a"]
        with self.assertRaisesRegex(AuditError, "cannot be relabeled"):
            validate_evaluation_plan(request["evaluation_plan"], request["question_persons"])

    def test_known_person_blind_record_rejected_before_trial(self):
        with tempfile.TemporaryDirectory() as tmp:
            card = proposal()
            request = fixture(card)
            request["evaluation_plan"]["person_provenance"]["new-person-a"] = "training_or_answer_seen"
            with self.assertRaisesRegex(AuditError, "hindsight_review"):
                trial(request, {"version":"v1", "rules":[card]}, Path(tmp)/"out.json", Path(tmp)/"registry")

    def test_missing_predeclared_gate_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            card = proposal()
            request = fixture(card)
            request.pop("evaluation_plan")
            card, frozen, score, registry = self.trial_and_score(tmp, request, card)
            with self.assertRaisesRegex(AuditError, "before freezing"):
                promote_rule(card, frozen, score, registry, external_receipt_verified=True)

    def test_rule_must_actually_be_in_frozen_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            card = proposal()
            with self.assertRaisesRegex(AuditError, "exactly match"):
                trial(fixture(card), {"version":"v1", "rules":[]}, Path(tmp)/"out.json", Path(tmp)/"registry")

    def test_listed_but_unapplied_rule_cannot_receive_trial_credit(self):
        with tempfile.TemporaryDirectory() as tmp:
            card = proposal()
            request = fixture(card)
            request["records"][0]["applied_rule_ids"] = []
            with self.assertRaisesRegex(AuditError, "declare application"):
                trial(request, {"version":"v1", "rules":[card]}, Path(tmp)/"out.json", Path(tmp)/"registry")

    def test_multiple_questions_do_not_count_as_multiple_people(self):
        with tempfile.TemporaryDirectory() as tmp:
            card = proposal()
            request = fixture(card)
            request["question_persons"]["sq2"] = "new-person-a"
            request["evaluation_plan"]["person_provenance"].pop("new-person-b")
            card, frozen, score, registry = self.trial_and_score(tmp, request, card)
            with self.assertRaisesRegex(AuditError, "too few new persons"):
                promote_rule(card, frozen, score, registry, external_receipt_verified=True)

    def test_a_favorable_fabricated_score_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            card, frozen, score, registry = self.trial_and_score(tmp)
            fabricated = Path(tmp)/"fabricated.json"
            create_new(fabricated, {"eligible_score":{"accuracy_on_full_denominator":1.0}})
            with self.assertRaisesRegex(AuditError, "registered"):
                promote_rule(card, frozen, fabricated, registry, external_receipt_verified=True)


if __name__ == "__main__":
    unittest.main()

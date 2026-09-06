"""Synthetic control/provenance regressions; no biography accuracy is measured."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from benchmark import AuditError, digest, load_json
from controlled_trial import (ARMS, CONDITIONS, POLICY, SCHEMA, make_views, prepare,
                              registered_plan, score, submit, validate_spec)


def fixture(root, repetitions=1):
    root = Path(root)
    (root / "skill").mkdir()
    (root / "skill" / "SKILL.md").write_text("Synthetic instructions; not divination evidence.", encoding="utf-8")
    (root / "fusion.md").write_text("Synthetic fixed policy: retain null when neither method discriminates.", encoding="utf-8")
    return {"schema_version": SCHEMA, "trial_id": "synthetic-controls",
        "skill_root": "skill", "fusion_policy_file": "fusion.md",
        "seed": 42, "repetitions": repetitions, "scoring_policy": POLICY,
        "context_policy": "isolated_no_keys_no_other_arms",
        "host": {"model_id": "synthetic-model", "model_version": "synthetic-v1",
                 "reasoning_effort": "high", "instructions_version": "synthetic-host-v1",
                 "max_output_tokens": 1000, "sampling": {"temperature": 0}},
        "known_development_person_ids": [],
        "person_provenance": {"p1": "synthetic", "p2": "synthetic"},
        "questions": [{"id": q, "person_id": p, "partition": "training",
            "stem": "Synthetic event question " + q, "stem_has_no_birth_or_chart": True,
            "options": {"opt1": "Synthetic option one", "opt2": "Synthetic option two",
                        "opt3": "Synthetic option three", "opt4": "Synthetic option four"}}
            for q, p in (("q1", "p1"), ("q2", "p2"), ("q3", "p1"))],
        "charts": {p: {"bazi": {"synthetic_value": p + "-bazi"},
                        "ziwei": {"synthetic_value": p + "-ziwei"}} for p in ("p1", "p2")}}


def payload(body, run_id):
    arm = body["mappings"][run_id]["arm"]
    choices = {"q1": "opt1", "q2": "opt1", "q3": "opt2"}
    if arm == "fusion":
        choices = {"q1": "opt1", "q2": None, "q3": "opt1"}
    records = []
    for qid, semantic in choices.items():
        mapping = body["mappings"][run_id]["display_to_semantic"][qid]
        display = next((k for k, value in mapping.items() if value == semantic), None)
        records.append({"question_id": qid, "primary": display,
                        "rationale": "Synthetic test choice, not a prediction."})
    return {"host": body["spec"]["host"], "skill_sha256": body["skill_snapshot"]["sha256"],
            "view_sha256": digest(body["views"][run_id]), "records": records}


class ControlledTrialTests(unittest.TestCase):
    def prepare(self, root, repetitions=1):
        spec = fixture(root, repetitions)
        registry, bundle = Path(root) / "registry", Path(root) / "bundle"
        prepare(spec, root, bundle, registry)
        manifest = bundle / "manifest.json"
        return spec, registry, manifest, registered_plan(manifest, registry)["body"]

    def test_four_arms_and_three_conditions_hide_charts_in_baseline(self):
        with tempfile.TemporaryDirectory() as root:
            views, maps = make_views(fixture(root))
            self.assertEqual(len(views), 12)
            for run_id, view in views.items():
                self.assertNotIn("run_id", view)
                self.assertEqual(len(view["view_id"]), 20)
                self.assertNotIn("condition", view)
                self.assertEqual(len(view["questions"]), 3)
                for q in view["questions"]:
                    if maps[run_id]["arm"] == "stem_only":
                        self.assertNotIn("charts", q)
                        self.assertNotIn("person_id", q)
                    else:
                        expected = {"bazi", "ziwei"} if maps[run_id]["arm"] == "fusion" else {maps[run_id]["arm"]}
                        self.assertEqual(set(q["charts"]), expected)

    def test_shuffle_preserves_person_clusters_and_is_nonidentity(self):
        with tempfile.TemporaryDirectory() as root:
            spec = fixture(root)
            views, maps = make_views(spec)
            mapping = maps["r001/shuffled_charts/bazi"]
            self.assertEqual(mapping["chart_donors"], {"p1": "p2", "p2": "p1"})
            qs = views["r001/shuffled_charts/bazi"]["questions"]
            self.assertEqual(qs[0]["charts"], qs[2]["charts"])
            self.assertEqual(qs[0]["charts"]["bazi"], spec["charts"]["p2"]["bazi"])
            original = maps["r001/original/bazi"]["display_to_semantic"]
            shuffled = maps["r001/shuffled_options/bazi"]["display_to_semantic"]
            for qid in original:
                self.assertEqual(set(original[qid].values()), set(shuffled[qid].values()))
                self.assertTrue(all(original[qid][k] != shuffled[qid][k] for k in original[qid]))

    def test_one_person_cannot_cross_development_and_test(self):
        with tempfile.TemporaryDirectory() as root:
            spec = fixture(root)
            spec["questions"][2]["partition"] = "test"
            with self.assertRaisesRegex(AuditError, "one partition"):
                validate_spec(spec)

    def test_known_history_cannot_be_declared_unseen(self):
        with tempfile.TemporaryDirectory() as root:
            spec = fixture(root)
            spec["known_development_person_ids"] = ["p1"]
            spec["person_provenance"]["p1"] = "unseen_declared"
            with self.assertRaisesRegex(AuditError, "Previously known"):
                validate_spec(spec)
            spec["person_provenance"]["p1"] = "known_development"
            validate_spec(spec)
            for q in spec["questions"]:
                if q["person_id"] == "p1":
                    q["partition"] = "test"
            with self.assertRaisesRegex(AuditError, "Known answers"):
                validate_spec(spec)

    def test_answer_payload_cannot_enter_model_views(self):
        for field in ("answers", "answer", "answer_key", "correct_choice"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as root:
                spec = fixture(root)
                spec["questions"][0][field] = "opt1"
                with self.assertRaises(AuditError):
                    make_views(spec)

    def test_baseline_birth_redaction_declaration_is_required(self):
        with tempfile.TemporaryDirectory() as root:
            spec = fixture(root)
            del spec["questions"][0]["stem_has_no_birth_or_chart"]
            with self.assertRaisesRegex(AuditError, "Curator"):
                make_views(spec)

    def test_all_runs_must_be_frozen_before_answer_file_is_read(self):
        with tempfile.TemporaryDirectory() as root:
            _, registry, manifest, body = self.prepare(root)
            run_id = next(iter(body["views"]))
            submit(manifest, run_id, payload(body, run_id), registry)
            with self.assertRaisesRegex(AuditError, "Freeze all"):
                score(manifest, Path(root) / "NONEXISTENT-keys.json", registry, Path(root) / "score.json")

    def test_repeat_plan_and_submissions_cannot_be_shopped(self):
        with tempfile.TemporaryDirectory() as root:
            spec, registry, manifest, body = self.prepare(root)
            with self.assertRaisesRegex(AuditError, "already registered"):
                prepare(spec, root, Path(root) / "second-bundle", registry)
            run_id = next(iter(body["views"]))
            submit(manifest, run_id, payload(body, run_id), registry)
            with self.assertRaisesRegex(AuditError, "already submitted"):
                submit(manifest, run_id, payload(body, run_id), registry)

    def test_host_version_and_live_artifact_changes_are_detected(self):
        with tempfile.TemporaryDirectory() as root:
            _, registry, manifest, body = self.prepare(root)
            run_id = next(iter(body["views"]))
            row = copy.deepcopy(payload(body, run_id))
            row["host"]["max_output_tokens"] = 2000
            with self.assertRaisesRegex(AuditError, "host differs"):
                submit(manifest, run_id, row, registry)
            (Path(root) / "skill" / "SKILL.md").write_text("Changed synthetic rules", encoding="utf-8")
            with self.assertRaisesRegex(AuditError, "Actual skill"):
                submit(manifest, run_id, payload(body, run_id), registry)

    def test_visible_prompt_tampering_is_detected(self):
        with tempfile.TemporaryDirectory() as root:
            _, registry, manifest, body = self.prepare(root)
            run_id = next(iter(body["views"]))
            path = manifest.parent / "views" / (body["views"][run_id]["view_id"] + ".json")
            current = load_json(path)
            current["questions"][0]["stem"] = "Changed test stem"
            path.write_text(json.dumps(current), encoding="utf-8")
            with self.assertRaisesRegex(AuditError, "visible prompt changed"):
                submit(manifest, run_id, payload(body, run_id), registry)

    def test_scoring_retains_abstentions_semantics_and_all_repetitions(self):
        with tempfile.TemporaryDirectory() as root:
            _, registry, manifest, body = self.prepare(root, repetitions=2)
            for run_id in body["views"]:
                submit(manifest, run_id, payload(body, run_id), registry)
            answers = Path(root) / "curator-keys.json"
            answers.write_text(json.dumps({q: "opt1" for q in ("q1", "q2", "q3")}), encoding="utf-8")
            result = score(manifest, answers, registry, Path(root) / "score.json")
            self.assertEqual(len(result["runs"]), 24)
            self.assertFalse(result["prediction_accuracy_validated"])
            for condition in CONDITIONS:
                current = result["runs"]["r001/" + condition + "/fusion"]
                m = current["all_rows_descriptive"]
                self.assertEqual((m["questions"], m["persons"], m["correct"], m["answered"]), (3, 2, 2, 2))
                self.assertAlmostEqual(m["accuracy_on_full_denominator"], 2 / 3)
                self.assertAlmostEqual(m["coverage"], 2 / 3)
                self.assertEqual(m["accuracy_among_answered"], 1)
                self.assertEqual(m["person_macro_accuracy"], 0.5)
                self.assertEqual(current["declared_unseen_test"]["questions"], 0)
                changes = result["comparisons_descriptive_all_rows"]["r001/" + condition + "/fusion_vs_bazi"]
                self.assertEqual((changes["changed_to_correct"], changes["changed_from_correct"]), (1, 1))
            aggregate = result["all_predeclared_repetitions"]["original/fusion"]
            self.assertEqual(aggregate["repetitions"], 2)
            self.assertEqual(aggregate["distinct_person_count_not_multiplied_by_repetitions"], 2)

    def test_cli_end_to_end_with_synthetic_inputs(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            spec = fixture(root)
            plan_path = root / "input.json"
            plan_path.write_text(json.dumps(spec), encoding="utf-8")
            script = Path(__file__).with_name("controlled_trial.py")
            registry, bundle = root / "registry", root / "bundle"
            def cli(*args):
                result = subprocess.run([sys.executable, str(script), *map(str, args), "--registry", str(registry)],
                                        capture_output=True, text=True, check=True)
                return json.loads(result.stdout)
            self.assertEqual(cli("prepare", "--input", plan_path, "--root", root, "--out", bundle)["runs"], 12)
            manifest = bundle / "manifest.json"
            body = registered_plan(manifest, registry)["body"]
            for i, run_id in enumerate(body["views"]):
                path = root / f"submission-{i}.json"
                path.write_text(json.dumps(payload(body, run_id)), encoding="utf-8")
                self.assertEqual(len(cli("submit", "--manifest", manifest, "--run-id", run_id,
                                         "--input", path)["submission_sha256"]), 64)
            keys = root / "curator-keys.json"
            keys.write_text(json.dumps({q: "opt1" for q in ("q1", "q2", "q3")}), encoding="utf-8")
            report = cli("score", "--manifest", manifest, "--answers", keys, "--out", root / "score.json")
            self.assertEqual(report["runs"], 12)
            self.assertFalse(report["prediction_accuracy_validated"])


if __name__ == "__main__":
    unittest.main()
